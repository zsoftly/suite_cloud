# Copyright (c) 2026, ZSoftly Technologies Inc. and contributors
# For license information, please see license.txt

"""Externally managed clusters: a Stalwart that something else installs and runs.

On Kubernetes, Argo CD (or any deployment tool) runs Stalwart with its data store, listeners and
certificates. Suite Cloud must not install packages over SSH there, write files on a node, or
point the server at a local resolver or log directory. It adopts the running server over the JMAP
management API instead, with the server's recovery administrator, and from then on manages the
same objects it manages on a cluster it installed: the default domain, system settings, roles,
the sending-limit backstop, and every tenant's domains, accounts, groups and mailing lists.

What stays with the platform on such a cluster: nodes, the store settings, listeners, TLS
certificates (no ACME provider), DNS resolution, logging, the outbound scanner and the
telemetry push (both need a per-node token or sidecar Suite Cloud does not install).
"""

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.utils import now

from suite_cloud.mail.cluster import plan
from suite_cloud.mail.stalwart import get_base_url, verify_tls
from suite_cloud.mail.stalwart.client import StalwartClient
from suite_cloud.mail.stalwart.connection import ConnectionInfo, JMAPConnection
from suite_cloud.mail.stalwart.errors import StalwartError

if TYPE_CHECKING:
    from frappe.model.document import Document

# The directory account Suite Cloud signs in as. Not "admin": that name is usually the server's
# recovery administrator, a virtual login that would shadow a directory account of the same name.
DEFAULT_ADMIN_USERNAME = "suite-admin"
HOSTNAME = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
ADOPTABLE_STATUSES = ("Pending", "Failed", "Active")


def is_external(target: "Document | None") -> bool:
    return bool(target is not None and target.get("externally_managed"))


def validate_cluster(cluster: "Document") -> None:
    if not cluster.externally_managed:
        return
    if cluster.is_new() and (cluster.admin_username or "admin") == "admin":
        cluster.admin_username = DEFAULT_ADMIN_USERNAME
    url = urlparse(cluster.base_url or "")
    if url.scheme not in ("http", "https") or not url.hostname:
        frappe.throw(_("Set the Base URL to the server's management URL, e.g. http://stalwart.mail.svc:8080."))
    if url.path not in ("", "/"):
        frappe.throw(_("The Base URL is the server's root URL, without a path."))
    if cluster.jmap_hostname:
        cluster.jmap_hostname = cluster.jmap_hostname.strip().lower().rstrip(".")
        if not HOSTNAME.match(cluster.jmap_hostname):
            frappe.throw(_("JMAP Service Hostname must be a host name without a scheme or port."))
    if not cluster.is_new() and frappe.db.exists("Stalwart Node", {"cluster": cluster.name}):
        frappe.throw(_("An externally managed cluster holds no Stalwart Nodes; remove them first."))


def validate_node(node: "Document", cluster: "Document") -> None:
    if is_external(cluster):
        frappe.throw(
            _("{0} is externally managed: its servers are deployed outside Suite Cloud.").format(cluster.name)
        )


def adoption_plan(cluster: "Document") -> list[dict]:
    """The cluster plan plus the permanent administrator, as the recovery stage applies it on a
    cluster Suite Cloud installs. The server already ran its first normal start, so its built-in
    roles and throttles exist and the disabled-accounts role and backstop can go in at once."""

    return [*plan.cluster_plan(cluster), plan.admin_account_operation(cluster, domain="#default")]


def adopt(cluster: "Document", username: str, password: str) -> dict:
    """Applies the adoption plan with the recovery administrator, mints Suite Cloud's API key with
    the permanent administrator, then marks the cluster active and pushes the full plan."""

    from suite_cloud.mail.cluster import bootstrap

    if not cluster.externally_managed:
        frappe.throw(_("Only an externally managed cluster can be adopted."))
    if cluster.status not in ADOPTABLE_STATUSES:
        frappe.throw(_("A cluster in status {0} cannot be adopted.").format(cluster.status))
    if not (username and password):
        frappe.throw(_("Give the server's recovery administrator and its password."))

    info = ConnectionInfo(
        get_base_url(cluster),
        username=username,
        password=password,
        verify_ssl=verify_tls(),
        pin_api_url=True,
    )
    try:
        recovery = StalwartClient(JMAPConnection(info))
        rendered = adoption_plan(cluster)
        result = recovery.apply(rendered)
        recovery.reload_settings()

        bootstrap.ensure_api_key(cluster, cluster.get_admin_client())
    except StalwartError as e:
        cluster.db_set({"status": "Failed", "last_config_sync_error": str(e)[:1000]}, update_modified=False)
        raise

    cluster.bump_config_version(rendered)
    cluster.db_set(
        {"status": "Active", "last_config_sync_at": now(), "last_config_sync_error": None},
        update_modified=False,
    )
    pushed = cluster.push_config()
    return {"adopted": result.created, "pushed": pushed}

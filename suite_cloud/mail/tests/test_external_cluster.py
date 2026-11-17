# Copyright (c) 2026, ZSoftly Technologies Inc. and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from suite_cloud.mail.cluster import bootstrap, external, plan
from suite_cloud.mail.stalwart.connection import ConnectionInfo, JMAPConnection, SessionStore
from suite_cloud.mail.tests.fake_stalwart import FakeStalwart
from suite_cloud.mail.tests.fixtures import configure_settings, make_cluster, make_node

BASE_URL = "http://stalwart.mail.svc.test:8080"
JMAP_HOST = "stalwart.mail.svc.test"
NODE_LOCAL = {"Tracer", "DnsResolver", "AcmeProvider", "WebHook", "Metrics", "MtaMilter", "MtaHook"}


def make_external_cluster(**fields):
    return make_cluster(
        "k8s-1",
        multi_node=False,
        externally_managed=1,
        base_url=BASE_URL,
        jmap_hostname=JMAP_HOST,
        **fields,
    )


class TestExternalCluster(IntegrationTestCase):
    def setUp(self) -> None:
        frappe.flags.do_not_enqueue = True
        configure_settings()

    def tearDown(self) -> None:
        frappe.flags.do_not_enqueue = False

    def test_an_external_cluster_keeps_its_url_and_needs_no_ssh(self) -> None:
        cluster = make_external_cluster()
        self.assertEqual(cluster.base_url, BASE_URL)
        self.assertFalse(cluster.ssh_public_key)
        # The recovery administrator is usually "admin"; Suite Cloud's own account must differ.
        self.assertEqual(cluster.admin_username, external.DEFAULT_ADMIN_USERNAME)

    def test_the_base_url_must_be_a_root_url(self) -> None:
        self.assertRaises(frappe.ValidationError, make_external_cluster, base_url="stalwart:8080")
        self.assertRaises(frappe.ValidationError, make_external_cluster, base_url=f"{BASE_URL}/jmap")

    def test_the_plan_leaves_what_the_platform_owns(self) -> None:
        cluster = make_external_cluster()
        rendered = plan.cluster_plan(cluster)
        objects = {op["object"] for op in rendered}
        self.assertFalse(objects & NODE_LOCAL, objects & NODE_LOCAL)
        settings = next(op for op in rendered if op["object"] == "SystemSettings")["value"]
        self.assertEqual(settings["services/jmap"], {"hostname": JMAP_HOST, "cleartext": False})
        domain = next(op for op in rendered if op["object"] == "Domain")["value"]["default"]
        self.assertEqual(domain["certificateManagement"], {"@type": "Manual"})
        # The sending-limit backstop stays: it needs no token on the server.
        backstop = [op for op in rendered if op["object"] == "MtaInboundThrottle"]
        self.assertEqual(len(backstop), 1)

        # A cluster Suite Cloud installs still gets every node-local object.
        installed = make_cluster("blr-2", hostname="mail.blr2.example.test", multi_node=False)
        self.assertTrue({"Tracer", "DnsResolver", "AcmeProvider"} <= {op["object"] for op in plan.cluster_plan(installed)})

    def test_an_external_cluster_takes_no_nodes(self) -> None:
        cluster = make_external_cluster()
        self.assertRaisesRegex(frappe.ValidationError, "externally managed", make_node, cluster)

    def test_a_pinned_connection_calls_the_base_url(self) -> None:
        session = {"apiUrl": "https://stalwart-0/jmap/", "capabilities": {}, "primaryAccounts": {}}
        store = SessionStore(get=lambda: session, set=lambda s: None, clear=lambda: None)
        pinned = JMAPConnection(ConnectionInfo(BASE_URL, token="t", pin_api_url=True), session_store=store)
        self.assertEqual(pinned.api_url, f"{BASE_URL}/jmap/")
        plain = JMAPConnection(ConnectionInfo(BASE_URL, token="t"), session_store=store)
        self.assertEqual(plain.api_url, "https://stalwart-0/jmap/")

    def test_adoption_applies_the_plan_with_the_recovery_admin_and_activates(self) -> None:
        cluster = make_external_cluster()
        fake = FakeStalwart(base_url=BASE_URL, admin_user="admin", admin_password="recovery-secret")
        with (
            fake.install(),
            patch.object(bootstrap, "ensure_api_key") as minted,
            patch.object(type(cluster), "push_config", return_value={"created": {}}) as pushed,
        ):
            result = external.adopt(cluster, "admin", "recovery-secret")
        minted.assert_called_once()
        pushed.assert_called_once()
        self.assertEqual(frappe.db.get_value("Stalwart Cluster", cluster.name, "status"), "Active")
        self.assertIn("admin", result["adopted"])  # the permanent administrator's plan reference
        self.assertTrue(
            any(a.get("name") == external.DEFAULT_ADMIN_USERNAME for a in fake.all("Account")),
            "the permanent administrator account was created",
        )

    def test_adoption_needs_an_external_cluster(self) -> None:
        installed = make_cluster("blr-3", hostname="mail.blr3.example.test", multi_node=False)
        self.assertRaises(frappe.ValidationError, external.adopt, installed, "admin", "x")

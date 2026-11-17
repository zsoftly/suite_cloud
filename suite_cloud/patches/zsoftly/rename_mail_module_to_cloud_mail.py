# Copyright (c) 2026, ZSoftly Technologies Inc. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.rename_doc import get_link_fields, update_link_field_values
from pypika.functions import Replace

# Frappe maps module names to apps across the whole bench, and Frappe Suite also has a "Mail"
# module: in a bench that carries both apps (Suite Cloud on its own site, Suite on another), every
# site resolved "Mail" to Suite Cloud and Frappe Mail's DocTypes stopped importing. The module is
# "Cloud Mail" again, its name before upstream renamed it. A site installed with "Mail" gets its
# links repointed and the old Module Def dropped, as the upstream patch did the other way round.
OLD = "Mail"
NEW = "Cloud Mail"


def execute() -> None:
    if not frappe.db.exists("Module Def", {"name": OLD, "app_name": "suite_cloud"}):
        return
    job = frappe.qb.DocType("Server Job")
    (
        frappe.qb.update(job)
        .set(job.variables_builder, Replace(job.variables_builder, "suite_cloud.mail.", "suite_cloud.cloud_mail."))
        .where(job.variables_builder.like("suite_cloud.mail.%"))
        .run()
    )
    update_link_field_values(get_link_fields("Module Def"), OLD, NEW, "Module Def")
    frappe.delete_doc("Module Def", OLD, force=True, ignore_missing=True)

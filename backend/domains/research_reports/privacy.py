"""Account export inventory and erasure for private saved research.

Keep report bodies out of the legacy export_jobs Mongo document: the combined
career export and research payload could exceed Mongo's document-size limit.
Each immutable report is available through its normal authenticated detail API.
"""
from domains.research_reports.service import ResearchReportService


async def report_export_index(db, user_id: str) -> dict:
    listing = await ResearchReportService(db.research_report_buckets).list(user_id)
    return {
        **listing,
        "content_included": False,
        "download_instructions": (
            "Report bodies are separate from this account export. In Research, "
            "choose Saved reports, open each report, then Download bundle. "
            "Each entry also includes its authenticated download API path."
        ),
        "reports": [
            {**report, "download_path": f"/api/v1/research/reports/{report['id']}"}
            for report in listing["reports"]
        ],
    }


async def erase_account_reports(db, user_id: str) -> None:
    # This collection uses a trusted principal as _id, not a user_id field.
    # Invoke only from the existing expired-account deletion workflow.
    await db.research_report_buckets.delete_one({"_id": user_id})

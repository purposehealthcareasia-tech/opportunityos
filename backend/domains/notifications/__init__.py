"""notifications domain package — standards-based Web Push (VAPID).

**Privacy invariant:** push payloads carry MINIMAL generic titles and bodies
only. No employer names, salaries, sealed / claim content, screener answers,
or authorization scope details EVER cross the push boundary. Details live
in-app after cookie authentication.
"""
NOTIFICATION_CATEGORIES = {
    "application_updates":     "Application updates (response / rejected / offer)",
    "interviews":              "Interviews scheduled or rescheduled",
    "approvals_expiring":      "Authorization approvals expiring soon",
    "receipts":                "New submission receipts",
    "support":                 "Support ticket replies",
}

"""Suffixed patterns are registered first. `me` is registered before `{jdg}`, and `new` before `{prj}`."""

from django.urls import path

from samepage.apps.portal import views

def fpath(route, view, name):
    return [
        path(route + ".<slug:fmt>", view.as_view(), name=name + "-fmt"),
        path(route, view.as_view(), name=name),
    ]


urlpatterns = []
urlpatterns += fpath("healthz", views.HealthView, "healthz")
urlpatterns += fpath("readyz", views.ReadyView, "readyz")
urlpatterns += fpath("", views.HomeView, "home")
# The sign-in, sign-up and set-password forms answer HTML only, so they have no .json or .csv twin.
urlpatterns += [path("login", views.LoginView.as_view(), name="login")]
urlpatterns += [path("logout", views.LogoutView.as_view(), name="logout")]
urlpatterns += [path("signup", views.SignupView.as_view(), name="signup")]
urlpatterns += [path("password/<slug:token>", views.PasswordLinkView.as_view(), name="password-link")]
urlpatterns += fpath("account", views.AccountView, "account")
urlpatterns += fpath("join/<slug:token>", views.JoinView, "join")
urlpatterns += fpath("accept/<slug:token>", views.AcceptRoleView, "accept-role")
urlpatterns += [path("demo/enter/<slug:slug>", views.DemoEnterView.as_view(), name="demo-enter")]
urlpatterns += fpath("about/access", views.AccessView, "access")
urlpatterns += fpath("e", views.HomeView, "events")
urlpatterns += [path("e/new", views.NewEventView.as_view(), name="event-new")]
urlpatterns += fpath("e/import", views.EventImportView, "event-import")
urlpatterns += fpath("e/<slug:evt>", views.EventView, "event")
urlpatterns += fpath("e/<slug:evt>/settings", views.EventSettingsView, "event-settings")
urlpatterns += fpath("e/<slug:evt>/state", views.EventStateView, "event-state")
urlpatterns += fpath("e/<slug:evt>/criteria", views.CriteriaView, "criteria")
urlpatterns += fpath("e/<slug:evt>/people", views.PeopleView, "people")
urlpatterns += fpath("e/<slug:evt>/people/<slug:person>/password-link", views.PasswordLinkIssueView, "password-link-issue")
urlpatterns += fpath("e/<slug:evt>/teams", views.TeamsView, "teams")
urlpatterns += fpath("e/<slug:evt>/teams/<slug:team>", views.TeamView, "team")
urlpatterns += fpath("e/<slug:evt>/teams/<slug:team>/invites", views.TeamInvitesView, "team-invites")
urlpatterns += fpath("e/<slug:evt>/teams/<slug:team>/invites/<slug:invite>/revoke", views.InviteRevokeView, "invite-revoke")
urlpatterns += fpath("e/<slug:evt>/teams/<slug:team>/leave", views.TeamLeaveView, "team-leave")
urlpatterns += fpath("e/<slug:evt>/teams/<slug:team>/members/<slug:person>/remove", views.TeamRemoveView, "team-remove")
urlpatterns += fpath("e/<slug:evt>/projects", views.ProjectsView, "projects")
urlpatterns += [path("e/<slug:evt>/projects/new", views.ProjectFormView.as_view(), name="project-new")]
urlpatterns += fpath("e/<slug:evt>/projects/<slug:prj>", views.ProjectView, "project")
urlpatterns += [path("e/<slug:evt>/projects/<slug:prj>/edit", views.ProjectFormView.as_view(), name="project-edit")]
urlpatterns += fpath("e/<slug:evt>/projects/<slug:prj>/submit", views.ProjectSubmitView, "project-submit")
urlpatterns += fpath("e/<slug:evt>/projects/<slug:prj>/withdraw", views.ProjectWithdrawView, "project-withdraw")
urlpatterns += fpath("e/<slug:evt>/projects/<slug:prj>/media", views.MediaUploadView, "media-upload")
urlpatterns += [path("e/<slug:evt>/projects/<slug:prj>/media/<int:media>", views.MediaView.as_view(), name="media")]
urlpatterns += fpath("e/<slug:evt>/projects/<slug:prj>/media/<int:media>/delete", views.MediaDeleteView, "media-delete")
urlpatterns += fpath("e/<slug:evt>/scores", views.ScoresView, "scores")
urlpatterns += fpath("e/<slug:evt>/progress", views.ProgressView, "progress")
urlpatterns += fpath("e/<slug:evt>/results", views.ResultsView, "results")
urlpatterns += fpath("e/<slug:evt>/publish", views.PublishView, "publish")
urlpatterns += fpath("e/<slug:evt>/normalization", views.LabView, "lab")
urlpatterns += fpath("e/<slug:evt>/normalization/<slug:table>", views.LabView, "lab-table")
urlpatterns += fpath("e/<slug:evt>/duplicates", views.DuplicatesView, "duplicates")
urlpatterns += fpath("e/<slug:evt>/duplicates/<slug:dup>", views.DuplicatesView, "duplicate")
urlpatterns += fpath("e/<slug:evt>/duplicates/<slug:dup>/confirm", views.DuplicateConfirmView, "duplicate-confirm")
urlpatterns += fpath("e/<slug:evt>/audit", views.AuditView, "audit")
urlpatterns += fpath("e/<slug:evt>/assignments", views.AssignmentsView, "assignments")
urlpatterns += fpath("e/<slug:evt>/assignments/<slug:jdg>/<slug:prj>/unlock", views.UnlockView, "unlock")
urlpatterns += fpath("e/<slug:evt>/assignment-runs", views.AssignmentListView, "runs")
urlpatterns += fpath("e/<slug:evt>/assignment-runs/<slug:run>", views.AssignmentRunView, "run")
urlpatterns += fpath("e/<slug:evt>/batches/<slug:batch>/abandon", views.AbandonView, "abandon")
urlpatterns += fpath("e/<slug:evt>/judge/batches", views.JudgeBatchesView, "judge-batches")
urlpatterns += fpath("e/<slug:evt>/judge/assignments/<slug:prj>", views.ConsoleView, "console")
urlpatterns += fpath("e/<slug:evt>/judge/assignments/<slug:prj>/scores", views.ConsoleSaveView, "console-save")
urlpatterns += fpath("e/<slug:evt>/judge/assignments/<slug:prj>/finalize", views.FinalizeView, "console-finalize")
urlpatterns += fpath("e/<slug:evt>/judges/me/scores", views.OwnScoresView, "own-scores")
urlpatterns += fpath("e/<slug:evt>/judges/<slug:jdg>/scores", views.NamedScoresView, "named-scores")

# Community voting (T3)
urlpatterns += fpath("e/<slug:evt>/voting", views.VotingView, "voting")
urlpatterns += fpath("e/<slug:evt>/voting/settings", views.VotingSettingsView, "voting-settings")
urlpatterns += fpath("e/<slug:evt>/voting/close", views.VotingCloseView, "voting-close")
urlpatterns += fpath("e/<slug:evt>/voting/tally", views.VotingTallyView, "voting-tally")
urlpatterns += fpath("e/<slug:evt>/voting/request-link", views.VotingRequestLinkView, "voting-request-link")
urlpatterns += [path("vote/<slug:token>", views.VoteOpenLinkView.as_view(), name="vote-open")]
urlpatterns += fpath("e/<slug:evt>/outbox", views.MailOutboxView, "mail-outbox")

# Public comments & pre-moderation (T3)
urlpatterns += fpath("e/<slug:evt>/projects/<slug:prj>/comments", views.ProjectCommentsView, "project-comments")
urlpatterns += fpath("e/<slug:evt>/comments", views.CommentsQueueView, "comments-queue")
urlpatterns += fpath("e/<slug:evt>/comments/<slug:cmt>/approve", views.CommentApproveView, "comment-approve")
urlpatterns += fpath("e/<slug:evt>/comments/<slug:cmt>/reject", views.CommentRejectView, "comment-reject")

# Signed records & judge protocols (T4 / S7)
urlpatterns += [
    path("e/<slug:evt>/records/root.txt", views.SignedRootRawView.as_view(), {"raw_fmt": "txt"}, name="signed-root-txt"),
    path("e/<slug:evt>/records/root.sig", views.SignedRootRawView.as_view(), {"raw_fmt": "sig"}, name="signed-root-sig"),
    path("e/<slug:evt>/records/pub.pem", views.SignedRootRawView.as_view(), {"raw_fmt": "pem"}, name="signed-root-pem"),
]
urlpatterns += fpath("e/<slug:evt>/records/root", views.SignedRootView, "signed-root")
urlpatterns += fpath("e/<slug:evt>/judge/protocol", views.JudgeProtocolView, "judge-protocol")

# Certificates (T4 / S8)
urlpatterns += [path("e/<slug:evt>/teams/<slug:team>/certificate.svg", views.TeamCertificateSvgView.as_view(), name="team-certificate-svg")]
urlpatterns += fpath("certificates/<slug:cert_no>", views.CertificateLookupView, "certificate-lookup")
urlpatterns += fpath("e/<slug:evt>/teams/<slug:team>/certificate", views.TeamCertificateView, "team-certificate")

# Feedback packs (T4 / S9)
urlpatterns += fpath("e/<slug:evt>/teams/<slug:team>/feedback", views.TeamFeedbackView, "team-feedback")
urlpatterns += fpath("e/<slug:evt>/feedback/release", views.FeedbackReleaseView, "feedback-release")
urlpatterns += fpath("e/<slug:evt>/feedback", views.AllFeedbackView, "all-feedback")

# Embed widget (T4 / S10)
urlpatterns += fpath("e/<slug:evt>/embed", views.EmbedWidgetView, "embed-widget")

# Webhooks (T4 / S12)
urlpatterns += fpath("e/<slug:evt>/webhooks", views.WebhooksView, "webhooks")
urlpatterns += fpath("e/<slug:evt>/webhooks/<slug:whep>/test", views.WebhookTestView, "webhook-test")
urlpatterns += fpath("e/<slug:evt>/events", views.EventFeedView, "event-feed")

# Bulk Import / Export (T4 / S13)
urlpatterns += fpath("e/<slug:evt>/export", views.EventExportView, "event-export")


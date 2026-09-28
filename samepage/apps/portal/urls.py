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
urlpatterns += [path("demo/enter/<slug:slug>", views.DemoEnterView.as_view(), name="demo-enter")]
urlpatterns += fpath("about/access", views.AccessView, "access")
urlpatterns += fpath("e", views.HomeView, "events")
urlpatterns += [path("e/new", views.NewEventView.as_view(), name="event-new")]
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

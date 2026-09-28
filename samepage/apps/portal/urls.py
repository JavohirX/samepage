"""Suffixed patterns are registered first. `me` is registered before `{jdg}`."""

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
# The sign-in form answers HTML only, so it has no .json or .csv twin (those URLs are 404).
urlpatterns += [path("login", views.LoginView.as_view(), name="login")]
urlpatterns += [path("logout", views.LogoutView.as_view(), name="logout")]
urlpatterns += [path("demo/enter/<slug:slug>", views.DemoEnterView.as_view(), name="demo-enter")]
urlpatterns += fpath("about/access", views.AccessView, "access")
urlpatterns += fpath("e", views.HomeView, "events")
urlpatterns += fpath("e/<slug:evt>", views.EventView, "event")
urlpatterns += fpath("e/<slug:evt>/projects", views.ProjectsView, "projects")
urlpatterns += fpath("e/<slug:evt>/projects/<slug:prj>", views.ProjectView, "project")
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
urlpatterns += fpath("e/<slug:evt>/assignment-runs", views.AssignmentListView, "runs")
urlpatterns += fpath("e/<slug:evt>/assignment-runs/<slug:run>", views.AssignmentRunView, "run")
urlpatterns += fpath("e/<slug:evt>/batches/<slug:batch>/abandon", views.AbandonView, "abandon")
urlpatterns += fpath("e/<slug:evt>/judge/batches", views.JudgeBatchesView, "judge-batches")
urlpatterns += fpath("e/<slug:evt>/judge/assignments/<slug:prj>", views.ConsoleView, "console")
urlpatterns += fpath("e/<slug:evt>/judge/assignments/<slug:prj>/scores", views.ConsoleSaveView, "console-save")
urlpatterns += fpath("e/<slug:evt>/judge/assignments/<slug:prj>/finalize", views.FinalizeView, "console-finalize")
urlpatterns += fpath("e/<slug:evt>/judges/me/scores", views.OwnScoresView, "own-scores")
urlpatterns += fpath("e/<slug:evt>/judges/<slug:jdg>/scores", views.NamedScoresView, "named-scores")

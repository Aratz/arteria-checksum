
from tornado.web import URLSpec as url

from arteria.web.app import AppService

from checksum.checksum_handlers import VersionHandler, StartHandler,\
        StatusHandler, StopHandler
from checksum.runner_service import RunnerService


def routes(**kwargs):
    """
    Setup routes and feed them any kwargs passed,
    e.g.`routes(config=app_svc.config_svc)` Help will be automatically
    available at /api, and will be based on the doc strings of the
    get/post/put/delete methods :param: **kwargs will be passed when
    initializing the routes.
    """

    return [
        url(r"/api/1.0/version", VersionHandler,
            name="version", kwargs=kwargs),
        url(r"/api/1.0/start/([\w_-]+)", StartHandler,
            name="start", kwargs=kwargs),
        url(r"/api/1.0/status/(\d*)", StatusHandler,
            name="status", kwargs=kwargs),
        url(r"/api/1.0/stop/([\d|all]*)", StopHandler,
            name="stop", kwargs=kwargs),
    ]


def start():
    """
    Start the checksum-ws app
    """

    app_svc = AppService.create(__package__)

    history_len = app_svc.config_svc["history_len"]
    runner_service = RunnerService(history_len=history_len)

    app_svc.start(routes(
        config=app_svc.config_svc,
        runner_service=runner_service))

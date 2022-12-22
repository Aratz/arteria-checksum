
import json
import logging
import os
import datetime


from arteria.exceptions import ArteriaUsageException
from arteria.web.state import State
from arteria.web.handlers import BaseRestHandler

from checksum import __version__ as version

log = logging.getLogger(__name__)

class BaseChecksumHandler(BaseRestHandler):
    """
    Base handler for checksum.
    """

    def initialize(self, config, runner_service):
        """
        Ensures that any parameters feed to this are available
        to subclasses.

        :param: config configuration used by the service
        :param: runner_service to use. Must fulfill `checksum.lib.jobrunner.JobRunnerAdapter` interface

        """
        self.config = config
        self.runner_service = runner_service


class VersionHandler(BaseChecksumHandler):

    """
    Get the version of the service
    """
    def get(self):
        """
        Returns the version of the checksum-service
        """
        self.write_object({"version": version })


class StartHandler(BaseChecksumHandler):

    """
    Validate that the runfolder exists under monitored directories
    :param runfolder: The runfolder to check for
    :param monitored_dir: The root in which the runfolder should exist
    :return: True if this is a valid runfolder
    """
    @staticmethod
    def _validate_runfolder_exists(runfolder, monitored_dir):
        if os.path.isdir(monitored_dir):
            sub_folders = [ name for name in os.listdir(monitored_dir)
                            if os.path.isdir(os.path.join(monitored_dir, name)) ]
            return runfolder in sub_folders
        else:
            return False

    @staticmethod
    def _validate_md5sum_path(runfolder, md5sum_file_path):
        """
        Checks if a `md5sum_file_path` is contained in the runfolder
        :param: runfolder path to the runfolder
        :param: md5sum_file_path path to the md5sum_file_path
        :return: True if `md5sum_file_path` is a file in the runfolder
        """
        common_prefix = os.path.commonprefix([runfolder, md5sum_file_path])
        is_sub_dir = common_prefix is runfolder

        return is_sub_dir and os.path.isfile(md5sum_file_path)

    @staticmethod
    def _is_valid_log_dir(log_dir):
        """
        Check if the log dir is valid. Right now only checks it is a directory.
        :param: log_dir to check
        :return: True is valid dir, else False
        """
        return os.path.isdir(log_dir)


    """
    Start a checksumming process.

    The request needs to pass the path the md5 sum file to check in "path_to_md5_sum_file". This path
    has to point to a file in the runfolder.

    :param runfolder: name of the runfolder we want to start checksumming for

    """
    async def post(self, runfolder):

        monitored_dir = self.config["monitored_directory"]
        StartHandler._validate_runfolder_exists(runfolder, monitored_dir)

        request_data = json.loads(self.request.body)

        path_to_runfolder = os.path.join(monitored_dir, runfolder)
        path_to_md5_sum_file = os.path.join(monitored_dir, runfolder, request_data["path_to_md5_sum_file"])

        if not StartHandler._validate_md5sum_path(path_to_runfolder, path_to_md5_sum_file):
            raise ArteriaUsageException("{} is not a valid file!".format(path_to_md5_sum_file))

        md5sum_log_dir = self.config["md5_log_directory"]

        if not StartHandler._is_valid_log_dir(md5sum_log_dir):
            raise ArteriaUsageException("{} is not a directory.!".format(md5sum_log_dir))

        md5sum_log_file = open(
            f"{md5sum_log_dir}/{runfolder}_{datetime.datetime.now().isoformat()}",
            mode='w')

        cmd = ["md5sum",  "-c", path_to_md5_sum_file]
        job_id = await self.runner_service.start(
                cmd,
                cwd=monitored_dir,
                stdout=md5sum_log_file,
                stderr=md5sum_log_file)

        status_end_point = "{0}://{1}{2}".format(
            self.request.protocol,
            self.request.host,
            self.reverse_url("status", job_id))

        response_data = {
                "job_id": job_id,
                "service_version": version,
                "link": status_end_point,
                "state": State.STARTED,
                "md5sum_log": md5sum_log_file.name}

        self.set_status(202, reason="started processing")
        self.write_object(response_data)


class StatusHandler(BaseChecksumHandler):
    """
    Get the status of one or all jobs.
    """

    def get(self, job_id):
        """
        Get the status of the specified job_id, or if now id is given, the
        status of all jobs.
        :param job_id: to check status for (set to empty to get status for all)
        """

        if job_id:
            status = {"state": self.runner_service.status(int(job_id))}
        else:
            all_status = self.runner_service.status_all()
            status_dict = {}
            for k,v in all_status.items():
                status_dict[k] = {"state": v}
            status = status_dict

        self.write_json(status)

class StopHandler(BaseChecksumHandler):
    """
    Stop one or all jobs.
    """

    def post(self, job_id):
        """
        Stops the job with the specified id.
        :param job_id: of job to stop, or set to "all" to stop all jobs
        """
        try:
            if job_id == "all":
                log.info("Attempting to stop all jobs.")
                self.runner_service.stop_all()
                log.info("Stopped all jobs!")
                self.set_status(200)
            elif job_id:
                log.info("Attempting to stop job: {}".format(job_id))
                self.runner_service.stop(int(job_id))
                self.set_status(200)
            else:
                ArteriaUsageException("Unknown job to stop")
        except ArteriaUsageException as e:
            log.warning("Failed stopping job: {}. Message: ".format(job_id, e.message))
            self.send_error(500, reason=e.message)


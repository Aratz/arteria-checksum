from arteria.web.state import State as arteria_state
import logging
import subprocess
import collections
import asyncio


log = logging.getLogger(__name__)


class Job:
    """
    Class used to run a command and keep track of its status

    Attributes
    ----------
    job_id: int
        id of the job
    cmd: [str]
        command to run

    Methods
    -------
    get_status()
        returns current status
    wait()
        wait for job to complete
    cancel()
        cancel current job
    """

    def __init__(self, job_id, cmd, **kwargs):
        """
        Parameters
        ----------
        job_id: int
            id of the job
        cmd: [str]
            command to run
        **kwargs:
            arguments to be forwarded to subprocess.Popen
        """
        self.job_id = job_id
        self.cmd = cmd
        self._status = arteria_state.STARTED
        log.info(f"Starting:\n job id: {job_id}\n cmd: {cmd}")
        log.debug(f"kwargs: {kwargs}")
        try:
            self._proc = subprocess.Popen(self.cmd, **kwargs)
        except Exception as e:
            log.error(e)
            raise

    def get_status(self):
        """
        Get job status.

        Can be one of the following from `arteria.web.state.State`:
            * `STARTED`
            * `DONE`
            * `ERROR`
            * `CANCELLED`
        """
        if self._status == arteria_state.STARTED:
            return_code = self._proc.poll()

            if return_code is None:
                self._status = arteria_state.STARTED
            elif return_code == 0:
                self._status = arteria_state.DONE
                log.info(
                    f"Job {self.job_id} completed successfully")
            else:
                self._status = arteria_state.ERROR
                log.error(
                    f"Job {self.job_id} failed with status code {return_code}")

        return self._status

    def wait(self):
        """
        Wait for the job to complete.
        """
        self._proc.wait()

    def cancel(self):
        """
        Cancel the job.
        """
        log.info(f"Cancelling job {self.job_id} (`{self.cmd}`)")
        self._proc.terminate()
        self._proc.wait()
        self._status = arteria_state.CANCELLED


class RunnerService:
    """
    Class to run and keep track of running jobs

    The jobs are kept in a rolling queue, when a new job is added and the
    queue is full, the oldest job is removed (provided it is not still
    running).

    Methods
    -------
    start(cmd, **kwargs):
        start a new job
    stop(job_id):
        stop job with given id
    stop_all:
        stop all running jobs
    status:
        return the status of the job with the given id
    status_all:
        return status of all jobs in the history
    """

    def __init__(self, history_len=100):
        """
        Parameters
        ----------
        history_len: int
            maximum number of jobs to keep track of.
        """
        self._job_history = collections.deque(maxlen=history_len)
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def _generate_next_id(self):
        """
        Returns a valid job id
        """
        async with self._lock:
            next_id = self._next_id
            self._next_id += 1
            return next_id

    def _get_job(self, job_id):
        """
        Returns the job with the given job id

        Parameters
        ----------
        job_id: int
            id of the desired job

        Raises
        ------
        IndexError
            when no job has the given id. This can mean the job never existed
            or is too old and was removed from memory.

        Returns
        -------
        Job
            job with the given job id
        """
        try:
            return next(
                job
                for job in self._job_history
                if job.job_id == job_id)
        except StopIteration:
            msg = f"job {job_id} not found"
            log.warning(msg)
            raise IndexError(msg)

    async def start(self, cmd, **kwargs):
        """
        Start executing a new command.

        Parameters
        ----------
        cmd: [str]
            command to be executed
        **kwargs:
            keyword arguments to be forwarded to subprocess.Popen

        Raises
        ------
        RuntimeError
            if the history is full and the oldest job is still running

        Returns
        -------
        job_id: int
        """
        if (
            self._job_history.maxlen == len(self._job_history)
            and self._job_history[-1].get_status() == arteria_state.STARTED
        ):
            msg = (
                "Could not start a new job because the history is full "
                "and the oldest job is still running."
                )
            log.error(msg)
            raise RuntimeError(msg)

        job_id = await self._generate_next_id()
        job = Job(job_id, cmd, **kwargs)

        async with self._lock:
            self._job_history.appendleft(job)

        return job.job_id

    def stop(self, job_id):
        """
        Stop the job with the given id.

        If no job with the given id is found, nothing is done.

        Parameters
        ----------
        job_id: int
            id of job to stop
        """
        try:
            self._get_job(job_id).cancel()
        except IndexError:
            pass

    def stop_all(self):
        """
        Stop all currently running jobs.
        """
        for job in self._job_history:
            job.cancel()

    def status(self, job_id):
        """
        Return the current status of the job with the given id.

        Can be one of the following from `arteria.web.state.State`:
            * `STARTED`
            * `DONE`
            * `ERROR`
            * `CANCELLED`
            * `NONE` (if the job was not found)

        Parameters
        ----------
        job_id: int
            id of the desired job

        Returns
        -------
        arteria.web.state.State

        """
        try:
            return self._get_job(job_id).get_status()
        except IndexError:
            return arteria_state.NONE

    def status_all(self):
        """
        Return the status of all jobs currently in the history.

        Returns
        -------
        {int: arteria.web.state.State}
        """
        return {
            job.job_id: job.get_status()
            for job in self._job_history
            }

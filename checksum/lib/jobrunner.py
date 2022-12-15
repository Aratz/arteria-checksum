from arteria.web.state import State as arteria_state
import logging
import subprocess
import collections
import asyncio


log = logging.getLogger(__name__)


class Job:
    def __init__(self, job_id, cmd, **kwargs):
        self.job_id = job_id
        self.cmd = cmd
        self._status = arteria_state.STARTED
        log.info(f"Starting new job with id {job_id} and command: `{cmd}`")
        try:
            self._proc = subprocess.Popen(self.cmd, **kwargs)
        except Exception as e:
            log.error(e)
            raise

    def get_status(self):
        if self._status == arteria_state.STARTED:
            return_code = self._proc.poll()

            if return_code is None:
                self._status = arteria_state.STARTED
            elif return_code == 0:
                self._status = arteria_state.DONE
            else:
                self._status = arteria_state.ERROR

        return self._status

    def wait(self):
        self._proc.wait()

    def cancel(self):
        log.info(f"Cancelling job {self.job_id} (`{self.cmd}`)")
        self._proc.terminate()
        self._proc.wait()
        self._status = arteria_state.CANCELLED


class ChecksumService:
    def __init__(self, history_len):
        self._job_history = collections.deque(maxlen=history_len)
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def _generate_next_id(self):
        async with self._lock:
            next_id = self._next_id
            self._next_id += 1
            return next_id

    def _get_job(self, job_id):
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
        if self._job_history.maxlen == len(self._job_history)\
                and self._job_history[-1].get_status() == arteria_state.STARTED:
            msg = "Could not start a new job because the queue is full"
            log.error(msg)
            raise RuntimeError(msg)

        job_id = await self._generate_next_id()
        job = Job(job_id, cmd, **kwargs)

        async with self._lock:
            self._job_history.appendleft(job)

        return job.job_id

    def stop(self, job_id):
        try:
            return self._get_job(job_id).cancel()
        except IndexError:
            pass

    def stop_all(self):
        for job in self._job_history:
            job.cancel()

    def status(self, job_id):
        try:
            return self._get_job(job_id).get_status()
        except IndexError:
            return arteria_state.NONE

    def status_all(self):
        return {
            job.job_id: job.get_status()
            for job in self._job_history
            }

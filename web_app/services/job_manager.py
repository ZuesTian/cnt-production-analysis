from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from models import Job


class JobManager:
    def __init__(self, session_factory: sessionmaker[Session], max_workers: int = 2):
        self.session_factory = session_factory
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cnt-job")
        self._futures: dict[str, Future[Any]] = {}
        self._lock = Lock()

    def recover_interrupted_jobs(self) -> int:
        with self.session_factory() as session:
            jobs = session.scalars(select(Job).where(Job.status.in_(["queued", "running"]))).all()
            for job in jobs:
                job.status = "failed"
                job.phase = "interrupted"
                job.progress = 100
                job.message = "服务重启，原后台作业已终止，请重新提交"
                job.error_code = "JOB_INTERRUPTED"
            session.commit()
            return len(jobs)

    def submit(self, job_id: str, callback: Callable[..., None], *args: Any) -> Future[Any]:
        future = self.executor.submit(callback, *args)
        with self._lock:
            self._futures[job_id] = future

        def discard(_: Future[Any]) -> None:
            with self._lock:
                self._futures.pop(job_id, None)

        future.add_done_callback(discard)
        return future

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)


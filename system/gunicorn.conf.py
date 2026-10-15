"""One shared E5 model, warmed inside the worker before accepting searches."""

bind = '0.0.0.0:5050'
workers = 1
worker_class = 'gthread'
threads = 4
timeout = 600
graceful_timeout = 120
accesslog = None  # Session IDs are capabilities; do not log request paths.
errorlog = '-'
control_socket_disable = True  # Container lifecycle is managed by Compose.


def post_worker_init(worker):
    app = worker.wsgi
    jobs = app.extensions['job_store'].filter_jobs({})
    if not jobs:
        raise RuntimeError('HELENA requires an imported job database before startup.')
    worker.log.info('Warming E5 and checking the document cache for %d jobs.', len(jobs))
    app.extensions['retriever'].search(jobs, 'Python SQL Datenanalyse', top_k=20)
    worker.log.info('HELENA is ready; E5 is loaded. No LLM request was made during startup.')

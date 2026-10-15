"""Build all E5 vectors incrementally, reporting progress for the browser UI."""
import argparse
import time

from app import BASE_DIR, project_path
from data_store import JobStore
from index_state import write_progress
from retrieval import HybridRetriever


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default='instance/real-jobs.sqlite3')
    parser.add_argument('--device', default='mps')
    parser.add_argument('--batch-size', type=int, default=16)
    args = parser.parse_args()
    database = project_path(args.database)
    store = JobStore(database)
    store.initialize()
    jobs = store.filter_jobs({})
    engine = HybridRetriever(BASE_DIR / '.cache/embeddings', device=args.device, batch_size=args.batch_size)
    started = time.monotonic()
    completed = 0
    previous = started
    write_progress(database, 0, len(jobs), 'building', 0)

    def progress(done, total):
        nonlocal completed, previous
        completed = done
        now = time.monotonic()
        write_progress(database, done, total, 'building', now - started)
        print(f'{done}/{total} | {now - started:.1f}s elapsed | batch {now - previous:.1f}s', flush=True)
        previous = now

    try:
        engine.warmup(jobs, progress=progress)
        write_progress(database, len(jobs), len(jobs), 'ready', time.monotonic() - started)
        print(f'READY: {len(jobs)} Stellen vollständig indexiert.', flush=True)
    except Exception as error:
        write_progress(database, completed, len(jobs), 'failed', time.monotonic() - started)
        print(f'Indexierung fehlgeschlagen: {type(error).__name__}. Bereits gespeicherte Vektoren bleiben erhalten.', flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()

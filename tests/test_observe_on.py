import threading
import unittest
import uuid

from reactivex.subject import Subject
from blrec.utils.operators.observe_on import observe_on_new_thread


class ObserveOnTests(unittest.TestCase):
    def test_ordered_completion(self):
        source = Subject()
        values, errors = [], []
        completed = threading.Event()
        subscription = source.pipe(observe_on_new_thread(queue_size=2)).subscribe(
            values.append, errors.append, completed.set)
        try:
            source.on_next(1)
            source.on_next(2)
            source.on_completed()
            self.assertTrue(completed.wait(1))
            self.assertEqual(values, [1, 2])
            self.assertEqual(errors, [])
        finally:
            subscription.dispose()

    def test_error_propagation(self):
        source = Subject()
        done = threading.Event()
        errors = []
        def on_error(error):
            errors.append(error)
            done.set()
        subscription = source.pipe(observe_on_new_thread()).subscribe(on_error=on_error)
        failure = ValueError('upstream failure')
        source.on_error(failure)
        self.assertTrue(done.wait(1))
        subscription.dispose()
        self.assertEqual(errors, [failure])

    def test_dispose_from_consumer_with_full_queue_does_not_deadlock(self):
        source = Subject()
        entered, release, disposed = (threading.Event() for _ in range(3))
        name = 'blrec-test-' + uuid.uuid4().hex
        values = []
        def consume(value):
            values.append(value)
            entered.set()
            release.wait(2)
            subscription.dispose()
            disposed.set()
        subscription = source.pipe(observe_on_new_thread(queue_size=1, thread_name=name)).subscribe(consume)
        source.on_next(1)
        self.assertTrue(entered.wait(1))
        source.on_next(2)  # Fill the queue while the consumer is in its callback.
        release.set()
        self.assertTrue(disposed.wait(1), 'disposing consumer deadlocked on its own queue')
        for thread in threading.enumerate():
            if thread.name == name:
                thread.join(1)
                self.assertFalse(thread.is_alive())
        self.assertEqual(values, [1])

    def test_dispose_unblocks_a_backpressured_producer(self):
        source = Subject()
        entered, release, produced, disposed = (threading.Event() for _ in range(4))
        def consume(value):
            entered.set()
            release.wait(2)
        subscription = source.pipe(observe_on_new_thread(queue_size=1)).subscribe(consume)
        source.on_next(1)
        self.assertTrue(entered.wait(1))
        source.on_next(2)
        def produce():
            source.on_next(3)
            produced.set()
        def dispose():
            subscription.dispose()
            disposed.set()
        producer = threading.Thread(target=produce, daemon=True)
        closer = threading.Thread(target=dispose, daemon=True)
        producer.start()
        self.assertFalse(produced.wait(0.05))
        closer.start()
        release.set()
        self.assertTrue(produced.wait(1))
        self.assertTrue(disposed.wait(1))
        producer.join(1)
        closer.join(1)

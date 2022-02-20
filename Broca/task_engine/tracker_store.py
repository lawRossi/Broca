"""
@Author: Rossi
Created At: 2021-01-30
"""

import pickle

import lmdb

from .tracker import DialogueStateTracker


class TrackerStore:
    def get_tracker(self, sender_id):
        pass
    
    def update_tracker(self, tracker):
        pass
    
    @classmethod
    def from_config(cls, config):
        return cls()


class InMemoryTrackerStore(TrackerStore):
    def __init__(self) -> None:
        super().__init__()
        self.trackers = {}
        self.agent = None

    def get_tracker(self, sender_id):
        tracker = self.trackers.get(sender_id)
        if tracker is None:
            tracker = DialogueStateTracker(sender_id, self.agent)
            self.trackers[sender_id] = tracker
        return tracker


class LmdbTrackerStore(TrackerStore):

    def __init__(self, db_path):
        self.env = lmdb.open(db_path, map_size=int(1e11))


    def get_tracker(self, sender_id):
        with self.env.begin(write=True) as txn:
            tracker = txn.get(sender_id.encode())
            if tracker is None:
                tracker = TrackerStore()
                txn.put(sender_id.encode(), tracker)
            else:
                tracker = pickle.loads(tracker)
            return tracker

    def update_tracker(self, tracker):
        sender_id = tracker.sender_id
        tracker = pickle.dumps(tracker)
        with self.env.begin(write=True) as txn:
            txn.put(sender_id.encode(), tracker)

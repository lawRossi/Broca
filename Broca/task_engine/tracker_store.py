"""
@Author: Rossi
Created At: 2021-01-30
"""

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

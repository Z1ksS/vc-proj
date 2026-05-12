from typing import Dict, List
from models.job import Job

class InMemoryStorage:
    def __init__(self):
        self.data: Dict[str, List[Job]] = {}

    def save(self, keyword: str, jobs: List[Job]):
        self.data[keyword] = jobs

    def get_all(self):
        return self.data
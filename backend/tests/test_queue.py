import importlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["QUEUE_DB"] = os.path.join(self.temp.name, "queue.db")
        os.environ["OPERATOR_KEY"] = "test-operator-key-at-least-16"
        import backend.main
        self.module = importlib.reload(backend.main)
        self.client = TestClient(self.module.app)
        self.client.__enter__()
        self.headers = {"Authorization": "Bearer " + os.environ["OPERATOR_KEY"]}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def take(self):
        response = self.client.post("/api/tickets", json={"request_id": str(uuid4())})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def next(self, desk):
        return self.client.post(f"/api/desks/{desk}/next", headers=self.headers)

    def test_fifo_four_desks_and_finish(self):
        tickets = [self.take() for _ in range(6)]
        for desk in range(1,5):
            called = self.next(desk)
            self.assertEqual(called.json()["id"], tickets[desk-1]["id"])
        self.assertEqual(self.next(1).status_code, 409)
        finished = self.client.post("/api/desks/1/finish", headers=self.headers,
                                   json={"ticket_id": tickets[0]["id"]})
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(self.next(1).json()["id"], tickets[4]["id"])
        stale = self.client.post("/api/desks/1/finish", headers=self.headers,
                                json={"ticket_id": tickets[0]["id"]})
        self.assertEqual(stale.status_code, 409)

    def test_parallel_assignment_and_idempotent_creation(self):
        token = str(uuid4())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.client.post("/api/tickets",
                               json={"request_id": token}).json(), range(8)))
        self.assertEqual(len({r["id"] for r in results}), 1)
        for _ in range(7):
            self.take()
        with ThreadPoolExecutor(max_workers=4) as pool:
            assigned = list(pool.map(lambda desk: self.next(desk).json(), range(1,5)))
        self.assertEqual(len({r["id"] for r in assigned}), 4)
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.next(1).status_code, range(4)))
        self.assertEqual(responses, [409]*4)

    def test_auth_cancel_pause_and_privacy(self):
        ticket = self.take()
        self.assertEqual(self.client.post("/api/desks/1/next").status_code, 401)
        self.assertEqual(self.client.post("/api/tickets/"+ticket["token"]+"/cancel").status_code, 200)
        second = self.take()
        public = self.client.get("/api/state").json()
        self.assertNotIn("token", public["waiting"][0])
        self.assertEqual(public["waiting"][0]["position"], 1)
        self.client.post("/api/desks/1/pause", json={"paused": True}, headers=self.headers)
        self.assertEqual(self.next(1).status_code, 409)
        self.client.post("/api/desks/1/pause", json={"paused": False}, headers=self.headers)
        self.assertEqual(self.next(1).json()["id"], second["id"])
        self.assertEqual(self.client.post("/api/tickets/"+second["token"]+"/cancel").status_code, 409)
        self.assertEqual(self.client.post("/api/tickets", json={"request_id": "bad"}).status_code, 422)
        self.assertEqual(self.next(5).status_code, 404)

    def test_persistence(self):
        ticket = self.take()
        self.module.initialize()
        self.assertEqual(self.client.get("/api/tickets/"+ticket["token"]).json()["number"], ticket["number"])


if __name__ == "__main__":
    unittest.main()

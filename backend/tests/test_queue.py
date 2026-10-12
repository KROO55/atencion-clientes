import importlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop('DATABASE_URL', None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["QUEUE_DB"] = os.path.join(self.temp.name, "queue.db")
        os.environ["OPERATOR_KEY"] = "test-operator-key-at-least-16"
        if os.environ.get('TEST_DATABASE_URL'):
            import psycopg
            from psycopg import sql
            from psycopg.conninfo import make_conninfo
            url = os.environ['TEST_DATABASE_URL']
            schema = 'test_queue_' + uuid4().hex
            with psycopg.connect(url) as conn:
                conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            def remove_schema():
                with psycopg.connect(url) as conn:
                    conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            self.addCleanup(remove_schema)
            os.environ['DATABASE_URL'] = make_conninfo(url, options='-c search_path=' + schema)
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
        self.assertEqual([t['desk_id'] for t in tickets], [1, 2, 3, 4, None, None])
        self.assertEqual([t['status'] for t in tickets], ['serving'] * 4 + ['waiting'] * 2)
        self.assertEqual(self.next(1).status_code, 409)
        finished = self.client.post("/api/desks/1/finish", headers=self.headers,
                                   json={"ticket_id": tickets[0]["id"]})
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.json()['next_ticket']['id'], tickets[4]['id'])
        self.assertEqual(self.client.get('/api/state').json()['waiting'][0]['id'], tickets[5]['id'])
        stale = self.client.post("/api/desks/1/finish", headers=self.headers,
                                json={"ticket_id": tickets[0]["id"]})
        self.assertEqual(stale.status_code, 409)

    def test_parallel_assignment_and_idempotent_creation(self):
        token = str(uuid4())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.client.post("/api/tickets",
                               json={"request_id": token}).json(), range(8)))
        self.assertEqual(len({r["id"] for r in results}), 1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            created = list(pool.map(lambda _: self.take(), range(7)))
        expected_ids = sorted([results[0]['id']] + [t['id'] for t in created])
        state = self.client.get('/api/state').json()
        assigned = [desk['ticket'] for desk in state['desks']]
        self.assertEqual(len({r["id"] for r in assigned}), 4)
        self.assertEqual(sorted(r['id'] for r in assigned), expected_ids[:4])
        with ThreadPoolExecutor(max_workers=4) as pool:
            finished = list(pool.map(lambda desk: self.client.post(
                f"/api/desks/{desk['id']}/finish", headers=self.headers,
                json={'ticket_id': desk['ticket']['id']}).json(), state['desks']))
        self.assertEqual(sorted(r['next_ticket']['id'] for r in finished), expected_ids[4:])
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.next(1).status_code, range(4)))
        self.assertEqual(responses, [409]*4)

    def test_auth_cancel_pause_and_privacy(self):
        self.client.post('/api/desks/1/pause', json={'paused': True}, headers=self.headers)
        active = [self.take() for _ in range(3)]
        self.assertEqual([t['desk_id'] for t in active], [2, 3, 4])
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
        self.assertEqual(self.client.get('/api/tickets/'+second['token']).json()['desk_id'], 1)
        self.assertEqual(self.client.post("/api/tickets/"+second["token"]+"/cancel").status_code, 409)
        self.assertEqual(self.client.post("/api/tickets", json={"request_id": "bad"}).status_code, 422)
        self.assertEqual(self.next(5).status_code, 404)

    def test_persistence(self):
        ticket = self.take()
        self.module.initialize()
        self.assertEqual(self.client.get("/api/tickets/"+ticket["token"]).json()["number"], ticket["number"])
        self.assertEqual(self.client.get('/api/tickets/'+ticket['token']).json()['desk_id'], 1)


if __name__ == "__main__":
    unittest.main()


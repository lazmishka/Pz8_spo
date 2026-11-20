from django.test import SimpleTestCase


class HealthEndpointTests(SimpleTestCase):
    def test_health_routes_return_ok(self):
        for path in ('/health', '/health/', '/healthz/'):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'status': 'ok'})

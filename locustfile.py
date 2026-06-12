import os
from locust import HttpUser, task, between, events
import logging

# Production-Ready Locust Script for Google Colab
# 
# Execution in Colab:
# !pip install locust
# !locust -f locustfile.py --headless -u 10 -r 2 --run-time 10m --host=https://your-production-app.railway.app

SESSION_COOKIE = os.environ.get("KDS_SESSION_COOKIE", "")
if not SESSION_COOKIE:
    logging.warning("No KDS_SESSION_COOKIE environment variable set. The load test may fail with 401/403 if authentication is required.")

class KDSScreenUser(HttpUser):
    # Simulate the debounced KDS frontend
    # 60 events/min = 1 update per second
    # With a 3-second debounce window + 500ms jitter, 
    # the maximum HTTP polling frequency per screen is once every ~3.0 - 3.5 seconds.
    wait_time = between(3.0, 3.5)
    
    def on_start(self):
        # Inject production session cookie to bypass login flow
        # In Colab, set: os.environ["KDS_SESSION_COOKIE"] = "sessionid=xyz123..."
        if SESSION_COOKIE:
            self.client.headers.update({"Cookie": SESSION_COOKIE})

    @task
    def poll_kds_endpoint(self):
        # Execute the HTTP GET against the refactored KDSPollView
        with self.client.get("/kds/poll/", catch_response=True) as response:
            if response.status_code == 429:
                response.failure("Rate Limited (429 HTTP)")
            elif response.status_code == 403:
                response.failure("Forbidden (403 HTTP) - Check Session Cookie")
            elif response.status_code != 200:
                response.failure(f"Failed with status {response.status_code}")
            else:
                response.success()

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("Starting KDS Load Test")
    print(f"Target Host: {environment.host}")
    print(f"Users (Screens): {environment.parsed_options.num_users}")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("Load Test Complete. Check Locust UI or CLI output for metrics.")

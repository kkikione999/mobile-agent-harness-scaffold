PYTHON ?= python3

.PHONY: check test run-smoke-android run-smoke-ios eval package-failure replay update-selectors query mcp

check:
	$(PYTHON) tools/check_repo.py
	$(PYTHON) -m unittest discover -s tests

test:
	$(PYTHON) -m unittest discover -s tests

run-smoke-android:
	$(PYTHON) tools/run_scenario.py --scenario scenarios/smoke/cold_start_android.json --platform android

run-smoke-ios:
	$(PYTHON) tools/run_scenario.py --scenario scenarios/smoke/cold_start_ios.json --platform ios

eval:
	@if [ -z "$(RUN_DIR)" ]; then echo "Usage: make eval RUN_DIR=runs/<run-id>"; exit 1; fi
	$(PYTHON) tools/evaluate_run.py --run-dir $(RUN_DIR)

package-failure:
	@if [ -z "$(RUN_DIR)" ]; then echo "Usage: make package-failure RUN_DIR=runs/<run-id>"; exit 1; fi
	$(PYTHON) tools/package_failure.py --run-dir $(RUN_DIR)

replay:
	@if [ -z "$(RUN_DIR)" ]; then echo "Usage: make replay RUN_DIR=runs/<run-id>"; exit 1; fi
	$(PYTHON) tools/replay_run.py --run-dir $(RUN_DIR)

update-selectors:
	@if [ -z "$(RUN_DIR)" ]; then echo "Usage: make update-selectors RUN_DIR=runs/<run-id>"; exit 1; fi
	$(PYTHON) tools/update_selectors.py --run-dir $(RUN_DIR)

query:
	@if [ -z "$(QUERY)" ]; then echo "Usage: make query QUERY='action=tap success=false'"; exit 1; fi
	$(PYTHON) tools/query_telemetry.py --query "$(QUERY)"

mcp:
	$(PYTHON) tools/mcp_server.py

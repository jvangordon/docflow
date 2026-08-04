# Databricks notebook source
# MAGIC %md
# MAGIC # DocFlow · process new documents
# MAGIC Runs automatically when a file lands in the inbox volume (file-arrival
# MAGIC trigger). It asks the DocFlow app to run its processing stage, exactly
# MAGIC as pressing **Process documents** would.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-sdk --upgrade
# MAGIC %restart_python

# COMMAND ----------

import json
import urllib.request

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
app = w.apps.get("docflow")
if not app.url:
    raise RuntimeError("the docflow app has no URL — is it running?")
req = urllib.request.Request(
    app.url.rstrip("/") + "/api/go",
    data=json.dumps({"stage": "process"}).encode(),
    headers={**w.config.authenticate(), "Content-Type": "application/json"},
    method="POST")
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        print("processing started:", json.loads(r.read() or b"{}"))
except urllib.error.HTTPError as e:
    if e.code == 409:
        print("a run is already in progress — the new files are in its inbox")
    else:
        raise

import os
import socket

from bson.objectid import ObjectId
from flask import Flask, jsonify, redirect, render_template, request, url_for
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
APP_VERSION = os.environ.get("APP_VERSION", "v1")

app = Flask(__name__)
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
todos = client.todo_db.todos

# Flipped by /fail so the liveness probe can be made to fail on purpose (Part 7).
healthy = True


@app.route("/")
def index():
    items = list(todos.find().sort("_id", -1))
    return render_template(
        "index.html", todos=items, version=APP_VERSION, hostname=socket.gethostname()
    )


@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    if title:
        todos.insert_one({"title": title, "done": False})
    return redirect(url_for("index"))


@app.route("/toggle/<id>", methods=["POST"])
def toggle(id):
    item = todos.find_one({"_id": ObjectId(id)})
    if item:
        todos.update_one({"_id": item["_id"]}, {"$set": {"done": not item["done"]}})
    return redirect(url_for("index"))


@app.route("/delete/<id>", methods=["POST"])
def delete(id):
    todos.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("index"))


@app.route("/health")
def health():
    """Liveness probe: is the Flask process itself OK?"""
    if not healthy:
        return jsonify(status="unhealthy"), 500
    return jsonify(status="ok", version=APP_VERSION)


@app.route("/ready")
def ready():
    """Readiness probe: can this pod reach MongoDB?"""
    try:
        client.admin.command("ping")
        return jsonify(status="ready")
    except Exception as e:
        return jsonify(status="not ready", error=str(e)), 503


@app.route("/fail", methods=["GET", "POST"])
def fail():
    """Make this pod's liveness probe fail, so Kubernetes restarts it."""
    global healthy
    healthy = False
    return jsonify(status="liveness will now fail", pod=socket.gethostname())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

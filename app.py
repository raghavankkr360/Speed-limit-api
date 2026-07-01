from flask import Flask
import pandas as pd

# Load datasets
chennai = pd.read_csv("Chennai_Speed_Limit.csv")
thiruvallur = pd.read_csv("Thiruvallur_speed_limit.csv")

app = Flask(__name__)

@app.route("/")
def home():
    return "Speed Limit API Running"

@app.route("/count")
def count():
    return {
        "chennai": len(chennai),
        "thiruvallur": len(thiruvallur)
    }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
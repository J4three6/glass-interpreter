"""Send one test caption to the Glass Interpreter Host."""
import argparse
import json
import os
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description="Send a test caption to the Host")
    parser.add_argument("text")
    parser.add_argument("--host", default=os.environ.get("GI_HOST_IP", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()
    payload = json.dumps({"text": args.text}, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"http://{args.host}:{args.port}/caption", data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST",
    )
    with urlopen(request, timeout=10) as response:
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()

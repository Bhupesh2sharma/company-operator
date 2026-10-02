import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def main():
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)

    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise ValueError("OPENAI_MODEL is missing from your configuration")

    client = OpenAI(timeout=30.0, max_retries=0)

    response = client.responses.create(
        model=model,
        input="Reply with exactly: Model connection successful",
        max_output_tokens=50,
        store=False,
    )

    print("Response:", response.output_text)
    print("Response status:", response.status)

    if response.usage:
        print("Input tokens:", response.usage.input_tokens)
        print("Output tokens:", response.usage.output_tokens)


if __name__ == "__main__":
    main()
"""Run UCSD's OpenAI SDK example with the model selected in the local .env."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def main() -> None:
    load_dotenv(Path.cwd() / ".env", override=False)
    with OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
        timeout=60.0,
        max_retries=0,
    ) as client:
        response = client.chat.completions.create(
            model=os.environ["TRITONAI_MODEL"],
            messages=[
                {"role": "user", "content": "Explain machine learning in one sentence."},
            ],
        )
        print(response.choices[0].message.content)
        if response.usage:
            print(f"Tokens: {response.usage.total_tokens}")


if __name__ == "__main__":
    main()

"""Phase 0 smoke test for Amazon Bedrock.

Proves four things in one run:
  1. Your CLI login works                     (who am I?)
  2. The least-privilege app role works       (assume it, like the deployed app will)
  3. A chat model answers                     (Converse API)
  4. An embedding model returns a vector      (InvokeModel)
and prints what the whole run cost.

Run:  make smoke-bedrock
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from kb_core.pricing import PRICES_AS_OF, cost_usd
from kb_core.settings import get_settings

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient


def main() -> int:
    s = get_settings()
    session = boto3.Session(region_name=s.aws_region)

    try:
        me = session.client("sts").get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        print(f"Not logged in to AWS: {exc}\nRun: aws login --profile kb-dev")
        return 1
    print(f"1. Logged in as      {me['Arn']}")

    if s.app_role_arn:
        # Deliberately do NOT call Bedrock with admin credentials. We borrow the
        # app's narrow role, so a permissions gap shows up now, not in production.
        creds = session.client("sts").assume_role(
            RoleArn=s.app_role_arn, RoleSessionName="phase0-smoke", DurationSeconds=900
        )["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=s.aws_region,
        )
        print(f"2. Assumed app role  {s.app_role_arn}")
    else:
        print("2. KB_APP_ROLE_ARN not set, using your own credentials (ok before tf-apply)")

    runtime = session.client("bedrock-runtime")

    try:
        return _call_models(runtime)
    except ClientError as exc:
        error = exc.response["Error"]
        print(f"\nBedrock refused the call: {error['Code']}\n  {error['Message']}")
        if error["Code"] == "AccessDeniedException":
            print("  If this model is not in var.bedrock_model_ids, that is the policy working.")
        return 1


def _call_models(runtime: BedrockRuntimeClient) -> int:
    s = get_settings()
    chat = runtime.converse(
        modelId=s.bedrock_chat_model,
        messages=[
            {
                "role": "user",
                "content": [{"text": "In one sentence, what is retrieval-augmented generation?"}],
            }
        ],
        inferenceConfig={"maxTokens": 80, "temperature": 0.2},
    )
    usage = chat["usage"]
    chat_cost = cost_usd(s.bedrock_chat_model, usage["inputTokens"], usage["outputTokens"])
    print(f"3. {s.bedrock_chat_model}")
    print(f"   answer : {chat['output']['message']['content'][0]['text'].strip()}")
    print(
        f"   tokens : {usage['inputTokens']} in / {usage['outputTokens']} out"
        f"   latency: {chat['metrics']['latencyMs']} ms   cost: ${chat_cost:.8f}"
    )

    emb = json.loads(
        runtime.invoke_model(
            modelId=s.bedrock_embed_model,
            body=json.dumps(
                {
                    "inputText": "Design for failure and nothing will fail.",
                    "dimensions": s.embed_dimensions,
                    "normalize": True,
                }
            ),
        )["body"].read()
    )
    emb_cost = cost_usd(s.bedrock_embed_model, emb["inputTextTokenCount"])
    print(f"4. {s.bedrock_embed_model}")
    print(
        f"   vector : {len(emb['embedding'])} dimensions, first 3 = {emb['embedding'][:3]}"
        f"   tokens: {emb['inputTextTokenCount']}   cost: ${emb_cost:.8f}"
    )

    total = chat_cost + emb_cost
    print(f"\nTotal for this run: ${total:.8f}  (prices as of {PRICES_AS_OF})")
    print(f"You could run this about {int(1 / total):,} times for $1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""用四条固定样例离线评估检索意图。在 backend 目录运行：

    python -m experiments.intent_eval_demo
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 指向 backend 目录

from dataclasses import dataclass

from app.services.errors import ExtractionError
from app.services.extract import parse_intent


@dataclass(frozen=True)
class Sample:
    question: str
    raw_output: str
    expected_query: str


SAMPLES = (
    Sample(
        question="订单退货时，寄回去的运费谁出？",
        raw_output='{"query": "退货运费承担", "top_k": 3}',
        expected_query="退货运费承担",
    ),
    Sample(
        question="电子发票的抬头能写公司名称吗？",
        raw_output='{"query": "电子发票下载流程"}',
        expected_query="电子发票公司抬头",
    ),
    Sample(
        question="会员积分会过期吗？",
        raw_output='{"query": "会员积分有效期", "top_k": 0}',
        expected_query="会员积分有效期",
    ),
    Sample(
        question="不再使用了，怎么注销账号？",
        raw_output='{"query": "账号注销流程", "top_k": 3',
        expected_query="账号注销流程",
    ),
    Sample(
        question="收货地址填错了，怎么修改？",
        raw_output='{"top_k": 3}',
        expected_query="修改收货地址",
    ),
    Sample(
        question="在哪里查看退款进度？",
        raw_output=" \t\n  ",
        expected_query="查询退款进度",
    ),
    Sample(
        question="怎么补开发票？",
        raw_output='["补开发票流程"]',
        expected_query="补开发票流程",
    ),
    Sample(
        question="怎么查看商品的保修期限？",
        raw_output='{"query": "商品保修期限", "top_k": 10}',
        expected_query="商品保修期限",
    ),
)


def main(samples: tuple[Sample, ...] = SAMPLES) -> None:
    valid_count = 0
    matched_count = 0

    for number, sample in enumerate(samples, start=1):
        print(f"\n样例 {number}：{sample.question}")
        print(f"  模拟模型输出：{sample.raw_output}")
        print(f"  预期检索词：{sample.expected_query}")

        try:
            intent = parse_intent(sample.raw_output)
        except ExtractionError as exc:
            print("  结构合格：否")
            print(f"  原因：{exc}")
            print("  检索词正确：未判定（结构不合格）")
            continue

        valid_count += 1
        matched = intent.query == sample.expected_query
        if matched:
            matched_count += 1

        print("  结构合格：是")
        print(f"  实际检索词：{intent.query}")
        print(f"  检索词正确：{'是' if matched else '否'}")

    print("\n批次汇总")
    print(f"  结构合格率：{valid_count}/{len(samples)}")
    match_rate = f"{matched_count}/{valid_count}" if valid_count else "未判定"
    print(f"  合格样例中的检索词匹配率：{match_rate}")


if __name__ == "__main__":
    main()

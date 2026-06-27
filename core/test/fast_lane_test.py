"""
JARVIS — Fast Lane Test (macOS)
Tests parse_intent and execute_intent from the ported fast_lane module.
Run from project root:  python core/test/fast_lane_test.py
"""

import sys
import os

# Add project root to path so we can import core.fast_lane
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from core.fast_lane import (
    parse_intent,
    execute_intent,
    process_fast_lane,
    try_trivial_fast_lane,
    extract_percentage,
    fuzzy_match,
)




def test_extract_percentage():
    print("\n=== Percentage Extraction Tests ===")
    tests = [
        ("set to 50%", 50),
        ("set to full", 100),
        ("set to half", 50),
        ("volume 80", 80),
        ("zero", 0),
    ]
    for text, expected in tests:
        result = extract_percentage(text)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{text}' → {result} (expected {expected})")


def test_parse_intent():
    print("\n=== Intent Parsing Tests ===")
    tests = [
        ("volume up", "system", "increase"),
        ("mute", "system", "mute"),
        ("brightness 50", "system", "set"),
        ("play shape of you by ed sheeran", "spotify", "play"),
        ("pause", "spotify", "pause"),
        ("next song", "spotify", "next"),
        ("open chrome", "app", "launch"),
        ("search for python tutorials", "browser", "search"),
        ("minimize this window", "window", "minimize"),
        ("copy", "file", "copy"),
        ("paste", "file", "paste"),
        ("open downloads", "file", "open"),
        ("convert 100 dollars to rupees", "conversion", "convert"),
        ("scan bluetooth devices", "bluetooth", "scan"),
        ("connect to my airpods", "bluetooth", "connect"),
    ]
    for text, expected_cat, expected_action in tests:
        intents = parse_intent(text)
        if intents:
            intent, entities = intents[0]
            cat = intent.get("category", "?")
            action = intent.get("action", "?")
            status = "✓" if cat == expected_cat and action == expected_action else "✗"
            print(f"  {status} '{text}' → {cat}/{action} (expected {expected_cat}/{expected_action})")
            if status == "✗":
                print(f"      entities: {entities}")
        else:
            print(f"  ✗ '{text}' → NO INTENT (expected {expected_cat}/{expected_action})")


def test_trivial_fast_lane():
    print("\n=== Trivial Fast Lane Tests ===")
    tests = [
        ("pause", True),
        ("next song", True),
        ("mute", True),
        ("volume 50", True),
        ("copy", True),
        ("what is the weather", False),
        ("tell me a joke", False),
    ]
    for text, expected_match in tests:
        matched, result = try_trivial_fast_lane(text)
        status = "✓" if matched == expected_match else "✗"
        extra = f" → '{result}'" if matched else ""
        print(f"  {status} '{text}' matched={matched}{extra} (expected matched={expected_match})")


def test_multi_action():
    print("\n=== Multi-Action Tests ===")
    tests = [
        "increase volume and increase brightness",
        "mute and minimize this window",
    ]
    for text in tests:
        intents = parse_intent(text)
        print(f"  '{text}' → {len(intents)} intents:")
        for intent, entities in intents:
            print(f"    - {intent.get('category')}/{intent.get('action')} {entities}")


def test_process_fast_lane():
    print("\n=== Process Fast Lane Integration Tests ===")
    tests = [
        "volume up",
        "pause",
        "open downloads",
        "convert 10 kilometers to miles",
    ]
    context = []
    for text in tests:
        handled, result = process_fast_lane(text, context)
        status = "✓" if handled else "✗"
        print(f"  {status} '{text}' → handled={handled}, result='{result}'")


if __name__ == "__main__":
    print("=" * 60)
    print("  JARVIS Fast Lane — macOS Test Suite")
    print("=" * 60)


    test_extract_percentage()
    test_parse_intent()
    test_trivial_fast_lane()
    test_multi_action()
    test_process_fast_lane()

    print("\n" + "=" * 60)
    print("  Tests complete.")
    print("=" * 60)

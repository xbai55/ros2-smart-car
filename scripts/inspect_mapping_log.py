"""Read a mapping session summary or export a selected full ROS input as JSONL.

Summary works without ROS; raw message export runs in the sourced vehicle ROS environment.
"""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--topic', action='append', help='export this topic; repeat for several topics')
    parser.add_argument('--start', type=float, default=0, help='seconds from the beginning of the recording')
    parser.add_argument('--duration', type=float, default=10, help='seconds of full messages to export')
    parser.add_argument('--output', type=Path, help='JSONL destination when exporting full input')
    args = parser.parse_args()
    summary = json.loads((args.session/'session.json').read_text(encoding='utf-8'))
    if not args.topic:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if not args.output or args.start < 0 or args.duration <= 0:
        parser.error('full input export requires --output, --start >= 0 and --duration > 0')
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    from rosidl_runtime_py.convert import message_to_ordereddict
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(args.session/'inputs'), storage_id='sqlite3'),
                rosbag2_py.ConverterOptions('', ''))
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    missing = set(args.topic) - types.keys()
    if missing:
        parser.error('topics absent from this recording: ' + ', '.join(sorted(missing)))
    classes = {topic: get_message(types[topic]) for topic in args.topic}
    first = None
    count = 0
    with args.output.open('w', encoding='utf-8') as output:
        while reader.has_next():
            topic, data, stamp = reader.read_next()
            if first is None:
                first = stamp
            elapsed = (stamp - first) / 1e9
            if elapsed > args.start + args.duration:
                break
            if elapsed < args.start or topic not in classes:
                continue
            msg = deserialize_message(data, classes[topic])
            row = {'topic': topic, 'type': types[topic], 'recorded_at_ns': stamp,
                   'elapsed_sec': elapsed, 'message': message_to_ordereddict(msg)}
            output.write(json.dumps(row, ensure_ascii=False, default=list) + '\n')
            count += 1
    print(f'Exported {count} complete messages to {args.output}')


if __name__ == '__main__':
    main()

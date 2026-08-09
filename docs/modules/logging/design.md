# RosBridge Pro Logging Design

## Boundary

The logging core is a portable C++17 component. Its public headers do not include ROS 2 or
spdlog headers. The ROS adapter is an optional layer that translates the rendered event into the
ROS 2 logging path, including `/rosout` when a node context is available.

The logger records facts about an operation. It does not decide whether a module is retried,
restarted, degraded, or stopped; those decisions belong to lifecycle and recovery components.

## Event model

Every event has a timestamp, level, module, event name, human-readable message, thread ID, and
optional source location. Additional data uses a flat typed key/value list with only null, boolean,
signed integer, unsigned integer, double, and string values. The file sink serializes all fields as
one JSON object per line. Console and ROS output render a compact human-readable summary.

Nested arbitrary JSON, large payloads, automatic object serialization, and complete trace/span
propagation are intentionally outside the first version.

## Backends and outputs

spdlog supplies the bounded asynchronous queue, worker, flush, and rotating-file primitives. The
SDK owns the event model, module-level filtering, configuration, and a fan-out sink that sends the
same event to:

1. a rotating JSONL file;
2. a human-readable console sink; and
3. an optional ROS 2 sink. The node-based adapter publishes directly to `/rosout` with
   `rclcpp::RosoutQoS`; the logger-only overload can use the native ROS logging path.

The three sinks have independent enablement and minimum levels. A process uses one primary file
and rotates it by size with a fixed retention count in the first version.

## Queue and failure policy

Normal DEBUG/INFO/WARN events use a bounded queue and may be dropped when the queue is full. The
drop counter is exposed for diagnostics. ERROR/FATAL events use a separate critical queue so that
normal high-rate output cannot starve failures. FATAL flushes pending output but does not abort the
process. Queue memory is bounded and normal application threads are never blocked indefinitely.

If the configured directory or file cannot be opened, the backend falls back to stderr and keeps a
non-recursive fallback state. Shutdown stops admission, drains queues, flushes, and releases the
worker. Sink failures are reported through fallback state rather than recursively logged.

## Configuration

Configuration is layered as defaults, startup JSON file, environment variables, and command-line
overrides. The first version supports global level, hierarchical module levels, per-sink levels,
file path/name, rotation limits, queue sizes, and sink enablement. Runtime ROS service reconfiguration
is deferred until a real use case establishes its thread-safety and access-control requirements.

## Lifecycle and thread safety

Initialization installs one process backend. Logger handles keep a shared backend reference and are
safe to copy; logging is safe from multiple application threads. Shutdown is idempotent and makes
subsequent logging a no-op. The ROS adapter must be installed while ROS is initialized and must
stop publishing before ROS shutdown.

## Verification

Core tests cover field/event behavior, filtering, JSONL serialization, rotation, queue overflow,
error recording, fallback, and shutdown. ROS tests cover adapter installation and `/rosout`
delivery. Benchmarks measure disabled logs, enabled logs, single/multi-thread output, and queue
pressure on the actual CI/development environment rather than asserting a hardware-independent
throughput number.

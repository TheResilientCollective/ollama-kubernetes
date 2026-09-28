#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Static


@dataclass
class RequestResult:
    number: int
    status: str
    latency_ms: float = 0.0
    output: str = ""


@dataclass
class RequestState:
    number: int
    status: str = "pending"
    latency_ms: float = 0.0
    output: str = ""
    streaming: bool = False

    @property
    def widget_id(self) -> str:
        return f"req-{self.number}"

    @property
    def header_id(self) -> str:
        return f"req-{self.number}-header"

    @property
    def output_id(self) -> str:
        return f"req-{self.number}-output"


class RequestGridApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #summary {
        height: auto;
        padding: 1 2;
        background: $panel;
    }

    #requests {
        height: 1fr;
    }

    .request-card {
        height: auto;
        border: solid green;
        padding: 1;
        margin: 1 0;
    }

    .request-card.pending {
        border: solid yellow;
    }

    .request-card.error {
        border: solid red;
    }

    .request-header {
        height: auto;
        layout: horizontal;
        padding: 0 1;
    }

    .request-output {
        height: 8;
        overflow: auto;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
    }

    #results-container {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        url: str,
        count: int,
        method: str,
        headers: dict[str, str],
        body: Any,
        timeout: float,
        stream: bool = False,
    ) -> None:
        super().__init__()
        self.url = url
        self.count = count
        self.method = method
        self.headers = headers
        self.body = body
        self.timeout = timeout
        self.stream = stream
        self.request_states: dict[int, RequestState] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Starting requests...", id="summary")
        with Vertical(id="results-container"):
            yield ScrollableContainer(id="requests")
        yield Footer()

    def make_header_content(self, state: RequestState) -> Text:
        if state.status == "pending":
            color = "yellow"
        elif state.status == "ERROR" or not state.status.isdigit() or not state.status.startswith("2"):
            color = "red"
        else:
            color = "green"

        status_text = state.status if state.status != "OK" else "200"
        latency_text = f"{state.latency_ms:.1f} ms" if state.latency_ms > 0 else "—"

        t = Text()
        t.append(f"#{state.number}  ", style="dim")
        t.append(status_text, style=f"bold {color}")
        t.append(f"  {latency_text}", style="dim")
        return t

    def make_card(self, state: RequestState) -> Container:
        status_cls = ""
        if state.status == "pending":
            status_cls = "pending"
        elif state.status == "ERROR" or not state.status.isdigit() or not state.status.startswith("2"):
            status_cls = "error"

        header = Static(
            self.make_header_content(state),
            id=state.header_id,
            classes="request-header",
        )
        output = Static(
            "",
            id=state.output_id,
            classes="request-output",
        )

        card = Container(
            header,
            output,
            id=state.widget_id,
            classes=f"request-card {status_cls}",
        )
        return card

    def update_request(self, state: RequestState) -> None:
        card = self.query_one(f"#{state.widget_id}", Container)
        header = self.query_one(f"#{state.header_id}", Static)
        output = self.query_one(f"#{state.output_id}", Static)

        status_cls = ""
        if state.status == "pending":
            status_cls = "pending"
        elif state.status == "ERROR" or not state.status.isdigit() or not state.status.startswith("2"):
            status_cls = "error"

        card.classes = f"request-card {status_cls}"
        header.update(self.make_header_content(state))
        output.update(state.output)

    def append_output(self, state: RequestState, chunk: str) -> None:
        state.output += chunk
        output_widget = self.query_one(f"#{state.output_id}", Static)
        output_widget.update(state.output)

    async def on_mount(self) -> None:
        requests_container = self.query_one("#requests", ScrollableContainer)

        for i in range(1, self.count + 1):
            state = RequestState(number=i)
            self.request_states[i] = state
            card = self.make_card(state)
            requests_container.mount(card)

        self.run_worker(self.send_requests(), exclusive=True)

    async def send_one(
        self,
        client: httpx.AsyncClient,
        request_number: int,
    ) -> RequestState:
        state = self.request_states[request_number]
        start = time.perf_counter()

        try:
            if self.stream:
                state.streaming = True

                async with client.stream(
                    self.method,
                    self.url,
                    json=self.body,
                    headers=self.headers,
                ) as response:
                    state.status = str(response.status_code)

                    async for chunk in response.aiter_text():
                        state.output += chunk
                        self.append_output(state, chunk)

            else:
                response = await client.request(
                    self.method,
                    self.url,
                    json=self.body,
                    headers=self.headers,
                )

                state.status = str(response.status_code)

                try:
                    output = json.dumps(response.json(), indent=2)
                except ValueError:
                    output = response.text

                state.output = output
                self.append_output(state, "")

            elapsed_ms = (time.perf_counter() - start) * 1000
            state.latency_ms = elapsed_ms
            self.update_request(state)

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            state.latency_ms = elapsed_ms
            state.status = "ERROR"
            state.output = f"{type(exc).__name__}: {exc}"
            self.update_request(state)

        return state

    async def send_requests(self) -> None:
        summary = self.query_one("#summary", Static)

        timeout = None

        async with httpx.AsyncClient(timeout=timeout) as client:
            tasks = [
                self.send_one(client, request_number)
                for request_number in range(1, self.count + 1)
            ]

            results = await asyncio.gather(*tasks)

        successful = sum(
            result.status.isdigit() and result.status.startswith("2")
            for result in results
        )

        summary.update(
            f"Completed {len(results)} requests — "
            f"{successful} successful, "
            f"{len(results) - successful} failed"
        )


def parse_headers(values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}

    for value in values:
        if ":" not in value:
            raise argparse.ArgumentTypeError(
                f"Invalid header {value!r}; expected 'Name: Value'"
            )

        name, header_value = value.split(":", 1)
        headers[name.strip()] = header_value.strip()

    return headers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send concurrent HTTP requests and display responses in a grid."
    )

    parser.add_argument("url", help="Endpoint URL")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=10,
        help="Number of requests to send; default: 10",
    )
    parser.add_argument(
        "-X",
        "--method",
        default=None,
        help="HTTP method; default: GET (or POST if --data is supplied)",
    )
    parser.add_argument(
        "--data",
        help="JSON request body",
    )
    parser.add_argument(
        "-H",
        "--header",
        action="append",
        default=[],
        metavar="NAME: VALUE",
        help="HTTP header; can be specified multiple times",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="Request timeout in seconds; default: 30",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream response output as it arrives",
    )

    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be greater than zero")

    if args.method is None:
        args.method = "POST" if args.data else "GET"

    try:
        body = json.loads(args.data) if args.data else None
    except json.JSONDecodeError as exc:
        parser.error(f"--data must contain valid JSON: {exc}")

    headers = parse_headers(args.header)

    RequestGridApp(
        url=args.url,
        count=args.count,
        method=args.method.upper(),
        headers=headers,
        body=body,
        timeout=args.timeout,
        stream=args.stream,
    ).run()


if __name__ == "__main__":
    main()
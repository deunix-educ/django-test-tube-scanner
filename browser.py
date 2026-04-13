#!/usr/bin/python3
import argparse, webbrowser

WEB_BROWSER_PATH = {
    'chromium': '/usr/bin/chromium --start-fullscreen %s',
    'chrome': '/usr/bin/google-chrome --start-fullscreen %s',
    'firefox': '/usr/bin/firefox --start-fullscreen %s',
}

def main(browser_path, url):
    webbrowser.get(browser_path).open(url)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Web browser service")
    parser.add_argument("--host", default="127.0.0.1", help=f"Host for HTTP server (default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help=f"Port for HTTP server (default: 8000)")
    parser.add_argument("--browser",  default="chromium", help=f"default browser: chromium")
    args = parser.parse_args()

    main(WEB_BROWSER_PATH.get(args.browser, 'chromium'), f'http://{args.host}:{args.port}/')


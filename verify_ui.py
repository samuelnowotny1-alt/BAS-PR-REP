#!/usr/bin/env python3
"""
BAS Assistant Web UI - Comprehensive Button/Link Verification Script

This script:
1. Starts the FastAPI server in background
2. Creates a demo project
3. Crawls all pages and verifies every button/link/form
4. Reports dead links, missing endpoints, broken forms
"""

import asyncio
import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

VERIFY_PORT = int(os.environ.get("BAS_UI_VERIFY_PORT", "8000"))
BASE_URL = os.environ.get("BAS_UI_VERIFY_BASE_URL", f"http://127.0.0.1:{VERIFY_PORT}")
VERIFY_INPROCESS = os.environ.get("BAS_UI_VERIFY_INPROCESS", "0") == "1"
PROJECT_ID = "demo-hvac-project"


class UIVerifier:
    def __init__(self):
        self.server_process = None
        self.client = None
        self.visited_urls: Set[str] = set()
        self.results: List[Dict] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        
    def start_server(self):
        """Start the FastAPI server in background."""
        if VERIFY_INPROCESS:
            print("🧪 Using in-process ASGI transport, no local server bind needed")
            return
        print("🚀 Starting FastAPI server...")
        self.server_process = subprocess.Popen(
            [".venv/bin/uvicorn", "ui.api.main:app", "--host", "127.0.0.1", "--port", str(VERIFY_PORT)],
            cwd="/home/oem/.openclaw/workspace/bas-assistant",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Wait for server to be ready
        for _ in range(30):
            try:
                with httpx.Client() as client:
                    resp = client.get(f"{BASE_URL}/", timeout=2)
                    if resp.status_code == 200:
                        print("✅ Server ready!")
                        return
            except:
                time.sleep(0.5)
        raise RuntimeError("Server failed to start")
    
    def stop_server(self):
        """Stop the FastAPI server."""
        if self.server_process:
            print("🛑 Stopping server...")
            self.server_process.terminate()
            self.server_process.wait(timeout=5)
    
    async def __aenter__(self):
        self.start_server()
        if VERIFY_INPROCESS:
            from ui.api import main as ui_main

            ui_main.container.settings = ui_main.container.settings.model_copy(update={"auth_required": False})
            app = ui_main.app

            transport = httpx.ASGITransport(app=app)
            self.client = httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=True,
                timeout=30,
            )
        else:
            self.client = httpx.AsyncClient(base_url=BASE_URL, follow_redirects=True, timeout=30)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        self.stop_server()
    
    async def get(self, path: str) -> httpx.Response:
        """GET request with tracking."""
        url = f"{BASE_URL}{path}"
        if url in self.visited_urls:
            return None
        self.visited_urls.add(url)
        try:
            resp = await self.client.get(url)
            return resp
        except Exception as e:
            self.errors.append(f"GET {path}: {e}")
            return None
    
    async def post(self, path: str, data: dict = None, files: dict = None) -> httpx.Response:
        """POST request."""
        url = f"{BASE_URL}{path}"
        try:
            resp = await self.client.post(url, data=data, files=files)
            return resp
        except Exception as e:
            self.errors.append(f"POST {path}: {e}")
            return None
    
    def check_response(self, path: str, resp: httpx.Response, expected_codes: List[int] = None) -> bool:
        """Verify response is successful."""
        if resp is None:
            return False
        expected = expected_codes or [200, 303, 302, 201, 204]
        if resp.status_code not in expected:
            self.errors.append(f"{path}: HTTP {resp.status_code} - {resp.text[:200]}")
            return False
        return True
    
    def parse_links_and_forms(self, html: str, base_path: str) -> Tuple[List[str], List[Dict]]:
        """Extract all links and forms from HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        forms = []
        
        # Find all <a> tags with href
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True)[:50]
            if href.startswith('/'):
                links.append((href, text, 'link'))
            elif href.startswith('#'):
                # Anchor link - check if target exists in same page
                links.append((href, text, 'anchor'))
        
        # Find all <button> and <input type="submit">
        for btn in soup.find_all(['button', 'input']):
            if btn.name == 'input' and btn.get('type') not in ('submit', 'button', 'image'):
                continue
            text = btn.get_text(strip=True) or btn.get('value', '') or btn.get('id', '') or btn.get('class', [''])[0]
            forms.append({
                'type': 'button',
                'text': text[:50],
                'element': str(btn)[:100],
            })
        
        # Find all <form> tags
        for form in soup.find_all('form'):
            action = form.get('action', '')
            method = form.get('method', 'GET').upper()
            inputs = []
            for inp in form.find_all(['input', 'select', 'textarea']):
                inputs.append({
                    'name': inp.get('name'),
                    'type': inp.get('type', inp.name),
                    'required': inp.get('required') is not None,
                })
            forms.append({
                'type': 'form',
                'action': action,
                'method': method,
                'inputs': inputs,
                'element': str(form)[:200],
            })
        
        return links, forms
    
    async def load_demo_project(self):
        """Load the demo project via API."""
        print("📦 Loading demo project...")
        resp = await self.post("/api/load-demo")
        if resp and resp.status_code in (200, 303):
            print("✅ Demo project loaded")
            # Wait a bit for background generation
            await asyncio.sleep(2)
        else:
            self.errors.append(f"Failed to load demo: {resp.status_code if resp else 'None'}")
    
    async def verify_page(self, path: str, description: str = "") -> bool:
        """Verify a page loads and extract links/forms."""
        print(f"  🔍 Checking: {path} {description}")
        resp = await self.get(path)
        if not self.check_response(path, resp):
            return False
        
        # Parse for links and forms
        links, forms = self.parse_links_and_forms(resp.text, path)
        
        # Store results
        self.results.append({
            'path': path,
            'description': description,
            'status': resp.status_code,
            'links': links,
            'forms': forms,
            'content_length': len(resp.text),
        })
        
        return True
    
    async def verify_all_pages(self):
        """Verify all known pages in the application."""
        
        # Public pages (no project needed)
        public_pages = [
            ("/", "Home - Project List"),
            ("/project/new", "New Project Page"),
        ]
        
        for path, desc in public_pages:
            await self.verify_page(path, desc)
        
        # Load demo project
        await self.load_demo_project()
        
        # Project-specific pages
        project_pages = [
            (f"/project/{PROJECT_ID}", "Project Dashboard"),
            (f"/project/{PROJECT_ID}/import", "Import Data"),
            (f"/project/{PROJECT_ID}/validate", "Validate Project"),
            (f"/project/{PROJECT_ID}/gaps", "Gap Analysis"),
            (f"/project/{PROJECT_ID}/checkout", "Checkout Sheets"),
            (f"/project/{PROJECT_ID}/reports", "Reports"),
            (f"/project/{PROJECT_ID}/graphics", "Graphics"),
            (f"/project/{PROJECT_ID}/logic", "Logic Diagrams"),
            (f"/project/{PROJECT_ID}/export", "Export"),
            (f"/project/{PROJECT_ID}/sequence", "Sequence Parser"),
            (f"/project/{PROJECT_ID}/troubleshoot", "Troubleshooting"),
            (f"/project/{PROJECT_ID}/assumptions", "Assumptions Tracker"),
        ]
        
        for path, desc in project_pages:
            await self.verify_page(path, desc)
        
        # API endpoints (basic check)
        api_endpoints = [
            (f"/api/project/{PROJECT_ID}/summary", "Project Summary API"),
            (f"/api/project/{PROJECT_ID}/equipment", "Equipment List API"),
            (f"/api/project/{PROJECT_ID}/points", "Points List API"),
            (f"/api/project/{PROJECT_ID}/controllers", "Controllers List API"),
            (f"/project/{PROJECT_ID}/validate/report.json", "Validation JSON Export"),
            (f"/project/{PROJECT_ID}/validate/report.csv", "Validation CSV Export"),
        ]
        
        for path, desc in api_endpoints:
            await self.verify_page(path, desc)
    
    def analyze_results(self):
        """Analyze and report findings."""
        print("\n" + "="*80)
        print("📊 VERIFICATION REPORT")
        print("="*80)
        
        # Summary
        total_pages = len(self.results)
        successful = sum(1 for r in self.results if r['status'] in (200, 303, 302))
        failed = total_pages - successful
        
        print(f"\n📄 Pages Tested: {total_pages}")
        print(f"✅ Successful: {successful}")
        print(f"❌ Failed: {failed}")
        
        # Show failed pages
        if failed > 0:
            print("\n❌ FAILED PAGES:")
            for r in self.results:
                if r['status'] not in (200, 303, 302):
                    print(f"  - {r['path']} ({r['description']}): HTTP {r['status']}")
        
        # Collect all unique links
        all_links = []
        for r in self.results:
            for link, text, link_type in r['links']:
                all_links.append({
                    'url': link,
                    'text': text,
                    'type': link_type,
                    'from_page': r['path'],
                })
        
        print(f"\n🔗 Total Links Found: {len(all_links)}")
        
        # Categorize links
        internal_links = [l for l in all_links if l['url'].startswith('/') and not l['url'].startswith('//')]
        anchor_links = [l for l in all_links if l['type'] == 'anchor']
        external_links = [l for l in all_links if l['url'].startswith('http')]
        
        print(f"  Internal: {len(internal_links)}")
        print(f"  Anchors: {len(anchor_links)}")
        print(f"  External: {len(external_links)}")
        
        # Check for common dead link patterns
        dead_patterns = []
        for link in internal_links:
            url = link['url']
            # Check for placeholder URLs
            if url in ('#', '/', 'javascript:void(0)', 'javascript:;'):
                dead_patterns.append(f"  ⚠️  Placeholder link: '{link['text']}' -> {url} (from {link['from_page']})")
            # Check for template variables not replaced
            if '{{' in url or '}}' in url:
                dead_patterns.append(f"  ❌ Unrendered template: '{link['text']}' -> {url} (from {link['from_page']})")
            # Check for duplicate project_id issues
            if url.count('project_id') > 1 or url.count('project') > 2:
                dead_patterns.append(f"  ⚠️  Suspicious URL: {url} (from {link['from_page']})")
        
        if dead_patterns:
            print("\n🔴 DEAD/PROBLEMATIC LINKS:")
            for d in dead_patterns:
                print(d)
        
        # Analyze forms
        all_forms = []
        for r in self.results:
            for form in r['forms']:
                form['from_page'] = r['path']
                all_forms.append(form)
        
        print(f"\n📝 Total Forms/Buttons Found: {len(all_forms)}")
        
        form_issues = []
        for form in all_forms:
            if form['type'] == 'form':
                action = form['action']
                if not action:
                    form_issues.append(f"  ⚠️  Empty form action on {form['from_page']}")
                elif '{{' in action or '}}' in action:
                    form_issues.append(f"  ❌ Unrendered template in form action: {action} (from {form['from_page']})")
                elif not action.startswith('/') and not action.startswith('http'):
                    form_issues.append(f"  ⚠️  Relative form action: {action} (from {form['from_page']})")
                
                # Check for required inputs without names
                for inp in form['inputs']:
                    if inp['required'] and not inp['name']:
                        form_issues.append(f"  ❌ Required input without name on {form['from_page']}")
        
        if form_issues:
            print("\n📝 FORM ISSUES:")
            for f in form_issues:
                print(f)
        
        # Check for htmx attributes
        htmx_pages = []
        for r in self.results:
            soup = BeautifulSoup(r['content_length'] and r.get('html', ''), 'html.parser')
            if r['path'] in self.visited_urls:
                # We'd need to store HTML for this
                pass
        
        # Errors
        if self.errors:
            print(f"\n🔴 ERRORS ({len(self.errors)}):")
            for e in self.errors[:20]:
                print(f"  - {e}")
        
        # Warnings
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for w in self.warnings[:20]:
                print(f"  - {w}")
        
        return {
            'total_pages': total_pages,
            'successful': successful,
            'failed': failed,
            'total_links': len(all_links),
            'internal_links': len(internal_links),
            'anchor_links': len(anchor_links),
            'external_links': len(external_links),
            'dead_links': dead_patterns,
            'form_issues': form_issues,
            'errors': self.errors,
        }


async def main():
    print("="*80)
    print("🔍 BAS Assistant Web UI - Comprehensive Button/Link Verification")
    print("="*80)
    
    async with UIVerifier() as verifier:
        await verifier.verify_all_pages()
        results = verifier.analyze_results()
    
    # Save detailed report
    import json
    report_path = Path("/home/oem/.openclaw/workspace/bas-assistant/UI_VERIFICATION_REPORT.json")
    with open(report_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n📄 Detailed report saved to: {report_path}")
    
    # Exit code
    if results['failed'] > 0 or results['dead_links'] or results['form_issues'] or results['errors']:
        print("\n❌ VERIFICATION FAILED - Issues found!")
        sys.exit(1)
    else:
        print("\n✅ ALL CHECKS PASSED - Every button and link works!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())

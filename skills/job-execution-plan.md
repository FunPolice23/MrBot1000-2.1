# MrBot1000 v2.0 - Job Platform Discovery & Execution Fix

## Issue: Subagents operate without real execution

### Current Problems:
1. JobSearch mentions platforms but doesn't search them
2. Coder reports changes but doesn't write files
3. Agent analyzes files that don't exist
4. Platform list is static, not dynamic

### Solutions Needed:

## 1. Dynamic Platform Discovery

### Main Model Task:
```
Task: "Discover active freelance platforms for coding work"
Action: Research platforms with API or web scraping capability
Output: JSON list of platforms with:
- name: "Upwork", "Fiverr", "Freelancer.com", etc.
- url: "https://upwork.com" 
- api_available: true/false
- contact_type: "api" or "scraping"
- rate_limit: "requests/minute"
- categories: ["web dev", "python", "ai", ...]
```

### Implementation:
- Replace hardcoded platform list with discovered list
- Add `discover_new_platforms()` method in job_search_worker
- Store discovered platforms in shared_context.json

## 2. Real Job Search Implementation

### JobSearch Worker Updates:
```python
def find_gigs(self):
    """Actually search discovered platforms"""
    gigs = []
    for platform in self.discovered_platforms:
        if platform.api_available:
            gigs.extend(self._search_api_platform(platform))
        else:
            gigs.extend(self._search_scraping_platform(platform))
    return gigs

def _search_api_platform(self, platform):
    """Search via API if available"""
    pass

def _search_scraping_platform(self, platform):
    """Scrape the platform for gigs"""
    pass
```

## 3. Executable Coder Actions

### Current: Coder only reports
### Fix: Coder actually writes files

```python
def execute_code_change(self, file_path, changes):
    """Actually write the code changes"""
    if not os.path.exists(file_path):
        self.log(f"SKIP: {file_path} doesn't exist")
        return False
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        new_content = self._apply_changes(content, changes)
        
        with open(file_path, 'w') as f:
            f.write(new_content)
        
        self.log(f"SUCCESS: Updated {file_path}")
        return True
    except Exception as e:
        self.log(f"ERROR: {e}")
        return False
```

## 4. Correct File Analysis

### Before: Analyze ALL files in ROOT
### After: Only analyze files that match the task

```python
def analyze_for_task(self, task_description):
    """Analyze only relevant files for the task"""
    relevant_files = self._find_relevant_files(task_description)
    return self._analyze_files(relevant_files)

def _find_relevant_files(self, task):
    """Find files actually related to task"""
    # Use LLM to identify which files are relevant
    # Only return files that exist
    pass
```

## Phase 1: Immediate Fixes

1. **Update manager.py** to only send tasks about existing files
2. **Fix job_search_worker.py** to actually search (even if just web search via LLM)
3. **Update coder.py** to actually write code changes
4. **Add platform discovery** as first task
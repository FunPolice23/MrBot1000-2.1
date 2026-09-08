"""
agents/document_scanner.py — Document scanning, analysis, and QA verification.

Provides:
1. PDF/text document scanning
2. Content extraction and analysis
3. Quality scoring before submission
4. Double-check verification system
"""

import os
import re
import json
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DocumentAnalysis:
    """Result of document analysis."""
    document_id: str
    title: str
    content: str
    word_count: int
    character_count: int
    readability_score: float  # 0-1, higher is better
    completeness_score: float  # 0-1, relative to expected
    quality_notes: List[str]
    suggestions: List[str]
    risk_level: str  # low, medium, high
    checksum: str
    analyzed_at: float = field(default_factory=time.time)


@dataclass
class WorkVerification:
    """Verification of completed work before submission."""
    work_id: str
    expected_outputs: List[str]
    actual_outputs: List[str]
    missing_items: List[str]
    quality_score: float  # 0-1
    issues: List[str]
    recommendations: List[str]
    can_submit: bool
    verified_at: float = field(default_factory=time.time)


class DocumentScanner:
    """Scans and analyzes documents for quality verification."""

    def __init__(self, quality_threshold: float = 0.7):
        self.quality_threshold = quality_threshold
        self._flesch_kincaid_words = {}  # Cache for readability

    def analyze_document(self, path: str, expected_word_count: int = None) -> DocumentAnalysis:
        """Analyze a document for quality and completeness."""
        
        # Read document content
        content = self._read_document(path)
        
        if not content:
            return DocumentAnalysis(
                document_id=os.path.basename(path),
                title="Error Document",
                content="",
                word_count=0,
                character_count=0,
                readability_score=0.0,
                completeness_score=0.0,
                quality_notes=["Could not read document"],
                suggestions=["Check file format and path"],
                risk_level="high",
                checksum=""
            )

        # Calculate metrics
        word_count = len(content.split())
        char_count = len(content)
        
        # Calculate readability
        readability = self._calculate_readability(content)
        
        # Calculate completeness
        if expected_word_count:
            completeness = min(1.0, word_count / expected_word_count)
        else:
            completeness = min(1.0, readability + 0.1)  # Estimate from readability

        # Identify issues
        notes, suggestions, risk = self._assess_quality(content, readability, completeness)

        # Generate checksum
        checksum = self._generate_checksum(content)

        return DocumentAnalysis(
            document_id=os.path.basename(path),
            title=os.path.basename(path),
            content=content,
            word_count=word_count,
            character_count=char_count,
            readability_score=readability,
            completeness_score=completeness,
            quality_notes=notes,
            suggestions=suggestions,
            risk_level=risk,
            checksum=checksum
        )

    def _read_document(self, path: str) -> str:
        """Read document content from various formats."""
        path_lower = path.lower()
        
        try:
            # PDF files
            if path_lower.endswith('.pdf'):
                return self._read_pdf(path)
            
            # Text files
            elif path_lower.endswith(('.txt', '.md', '.csv')):
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            
            # JSON files
            elif path_lower.endswith('.json'):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return json.dumps(data, indent=2)
            
            # Try as text file
            else:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
                    
        except Exception as e:
            print(f"[DocumentScanner] Error reading {path}: {e}")
            return ""

    def _read_pdf(self, path: str) -> str:
        """Extract text from PDF using pymupdf or basic extraction."""
        try:
            # Try pymupdf first
            import fitz  # pymupdf
            doc = fitz.open(path)
            text = ""
            for page in doc:
                text += page.get_text()
            return text
        except ImportError:
            # Fallback: try PyPDF2
            pass
        
        try:
            import PyPDF2
            with open(path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
            return text
        except ImportError:
            # Last resort: basic text extraction
            print("[DocumentScanner] Warning: No PDF library available, content may be incomplete")
            return ""
        except Exception as e:
            print(f"[DocumentScanner] PDF read error: {e}")
            return ""

    def _calculate_readability(self, text: str) -> float:
        """Calculate Flesch-Kincaid readability score (0-1)."""
        sentences = len(re.split(r'[.!?]+', text))
        words = len(text.split())
        syllables = self._count_syllables(text)
        
        if sentences == 0 or words == 0:
            return 0.5
        
        # Flesch Reading Ease: 206.835 - 1.015*(words/sentences) - 84.6*(syllables/words)
        score = 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)
        # Normalize to 0-1 (0=very hard, 100=very easy)
        return max(0, min(1, score / 100))

    def _count_syllables(self, text: str) -> int:
        """Estimate syllable count."""
        count = 0
        vowels = "aeiouy"
        
        for word in text.split():
            word = word.lower().strip(".,!?")
            if len(word) <= 3:
                count += 1
                continue
            
            # Count vowel groups
            syllable_count = 0
            prev_was_vowel = False
            
            for char in word:
                is_vowel = char in vowels
                if is_vowel and not prev_was_vowel:
                    syllable_count += 1
                prev_was_vowel = is_vowel
            
            # Silent 'e' at end
            if word.endswith('e') and syllable_count > 1:
                syllable_count -= 1
            
            count += max(1, syllable_count)
        
        return count

    def _assess_quality(self, content: str, readability: float, completeness: float) -> Tuple[List[str], List[str], str]:
        """Assess document quality and return notes, suggestions, and risk."""
        notes = []
        suggestions = []
        risk = "low"

        # Check minimum content
        if len(content) < 100:
            notes.append("Document is very short")
            suggestions.append("Add more detail and context")
            risk = "high"
        elif len(content) < 500:
            notes.append("Document is brief")
            suggestions.append("Consider adding examples or elaboration")

        # Check readability
        if readability < 0.3:
            notes.append("Readability may be too low")
            suggestions.append("Simplify language and shorten sentences")
            if risk != "high":
                risk = "medium"

        # Check for common issues
        if re.search(r'\{.*?\}', content):
            notes.append("Markdown/template placeholders found")
            suggestions.append("Review and fill in all placeholders")

        if re.search(r'\b(placeholder|todo|tbd|xxx)\b', content, re.I):
            notes.append("Incomplete content markers found")
            suggestions.append("Fill in all placeholders before submission")
            if risk != "high":
                risk = "medium"

        # Check completeness
        if completeness < 0.5:
            notes.append(f"Completeness low: {completeness:.1%}")
            suggestions.append("Add missing sections or details")
            risk = "high"

        return notes, suggestions, risk

    def _generate_checksum(self, content: str) -> str:
        """Generate checksum for content verification."""
        import hashlib
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def verify_completion(self, work_id: str, expected_outputs: List[str],
                         actual_files: List[str]) -> WorkVerification:
        """Verify that all expected outputs are present and complete."""
        
        missing = []
        issues = []
        quality_scores = []
        
        for expected in expected_outputs:
            found = False
            for actual in actual_files:
                if expected.lower() in actual.lower():
                    found = True
                    
                    # Analyze the found file
                    analysis = self.analyze_document(actual)
                    quality_scores.append(analysis.readability_score * 0.5 + analysis.completeness_score * 0.5)
                    
                    if analysis.risk_level == "high":
                        issues.append(f"{expected} has quality issues")
                    break
            
            if not found:
                missing.append(expected)
        
        # Calculate overall quality
        overall_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        
        # Determine if can submit
        can_submit = (
            len(missing) == 0 and
            overall_quality >= self.quality_threshold and
            len([i for i in issues if 'quality' in i.lower()]) == 0
        )
        
        # Generate recommendations
        recommendations = []
        if missing:
            recommendations.append(f"Complete missing outputs: {', '.join(missing)}")
        if overall_quality < self.quality_threshold:
            recommendations.append(f"Improve quality score (current: {overall_quality:.2%})")
        if issues:
            recommendations.extend(issues)

        return WorkVerification(
            work_id=work_id,
            expected_outputs=expected_outputs,
            actual_outputs=actual_files,
            missing_items=missing,
            quality_score=overall_quality,
            issues=issues,
            recommendations=recommendations,
            can_submit=can_submit
        )


class QualityController:
    """Controls quality gates before work submission."""

    def __init__(self, min_quality: float = 0.8, require_reviews: int = 0):
        self.min_quality = min_quality
        self.require_reviews = require_reviews
        self._reviewers = {}  # reviewer_id -> skills

    def pre_submit_check(self, work_files: List[str], 
                        expected_outputs: List[str]) -> Dict:
        """Run all quality checks before allowing submission."""
        
        scanner = DocumentScanner(self.min_quality)
        verification = scanner.verify_completion(
            "pre_submit", expected_outputs, work_files
        )
        
        return {
            "passed": verification.can_submit,
            "quality_score": verification.quality_score,
            "min_required": self.min_quality,
            "missing_items": verification.missing_items,
            "issues": verification.issues,
            "recommendations": verification.recommendations,
            "files_analyzed": len(work_files)
        }

    def double_check(self, work_files: List[str], 
                    review_by_ai: bool = True) -> Dict:
        """Double-check work using multiple verification methods."""
        
        results = {}
        
        # 1. Document analysis
        scanner = DocumentScanner()
        for f in work_files:
            analysis = scanner.analyze_document(f)
            results[f] = {
                "analysis": analysis.__dict__,
                "quality_pass": analysis.readability_score >= 0.5
            }
        
        # 2. Content consistency check
        if len(work_files) > 1:
            results["consistency"] = self._check_consistency(work_files)
        
        # 3. Risk assessment
        results["overall_risk"] = "low" if all(
            r.get("quality_pass", False) for r in results.values() 
            if isinstance(r, dict) and "quality_pass" in r
        ) else "medium"
        
        return results

    def _check_consistency(self, files: List[str]) -> Dict:
        """Check if files are consistent with each other."""
        checksums = []
        for f in files:
            scanner = DocumentScanner()
            analysis = scanner.analyze_document(f)
            checksums.append(analysis.checksum)
        
        # Check for duplicates
        unique_checksums = set(checksums)
        
        return {
            "unique_files": len(unique_checksums) == len(files),
            "duplicate_count": len(files) - len(unique_checksums)
        }


if __name__ == "__main__":
    # Demo
    scanner = DocumentScanner()
    
    # Create a sample document
    sample_path = "/tmp/sample_test.txt"
    with open(sample_path, 'w') as f:
        f.write("This is a test document for quality analysis. " * 50)
    
    analysis = scanner.analyze_document(sample_path)
    print(f"Document Analysis:")
    print(f"  Words: {analysis.word_count}")
    print(f"  Readability: {analysis.readability_score:.2%}")
    print(f"  Completeness: {analysis.completeness_score:.2%}")
    print(f"  Risk: {analysis.risk_level}")
    
    # Quality controller test
    qc = QualityController()
    check = qc.pre_submit_check([sample_path], ["Sample output"])
    print(f"\nPre-submit check: {'PASSED' if check['passed'] else 'FAILED'}")
    print(f"Recommendations: {check['recommendations']}")
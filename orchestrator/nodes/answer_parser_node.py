"""
Answer Parser Node - parses user answers from messages and updates questions.md.
"""

import os
import time
import json
import re
from typing import Optional, Any, Dict
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from orchestrator.state import (
    SharedState, 
    answer_question, 
    all_questions_answered,
    get_current_stage,
    check_retry_limit,
    handle_error_with_retry_budget
)
from orchestrator.tools.spec_feature_tools import (
    read_spec_file,
    write_spec_file,
)

# Configuration
MODEL_NAME = "gemini-2.5-flash-lite"

def _ensure_api_configured() -> bool:
    """Ensures API is configured. Returns True if successful."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY environment variable is not set. "
            "Please set it in your .env file or environment."
        )
    genai.configure(api_key=api_key)
    return True

def _call_api_with_retry(chat, prompt: str, max_retries: int = 3) -> Optional[Any]:
    """Calls API with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            response = chat.send_message(prompt)
            return response
        except google_exceptions.ResourceExhausted as e:
            wait_time = 2 ** attempt
            print(f"Rate limit hit. Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        except google_exceptions.ServiceUnavailable as e:
            wait_time = 2 ** attempt
            print(f"Service unavailable. Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        except Exception as e:
            print(f"API Error: {e}")
            raise
    raise Exception(f"API call failed after {max_retries} retries")

def _get_last_user_message(messages) -> str:
    """Return the most recent user message content."""
    for msg in reversed(messages or []):
        if hasattr(msg, "type") and getattr(msg, "type") == "human":
            return str(getattr(msg, "content", ""))
        if isinstance(msg, dict) and msg.get("role") == "user":
            return str(msg.get("content", ""))
    if messages:
        last = messages[-1]
        return str(getattr(last, "content", last))
    return ""

def _parse_question_number(user_msg: str) -> Optional[int]:
    """Try to extract question number from user message."""
    # Look for patterns like "#1", "question 1", "q1", "question1"
    patterns = [
        r'#(\d+)',
        r'question\s*(\d+)',
        r'q\s*(\d+)',
        r'question(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, user_msg, re.IGNORECASE)
        if match:
            return int(match.group(1))
    
    return None

def _match_answer_to_question_with_llm(user_msg: str, questions: list) -> Optional[Dict[str, Any]]:
    """Use LLM to match user answer to the correct question."""
    _ensure_api_configured()
    
    questions_list = []
    for i, q in enumerate(questions, 1):
        if q.get("status") == "open":
            question_text = q.get("question", "")
            question_id = q.get("id", "")
            questions_list.append({
                "number": i,
                "id": question_id,
                "question": question_text
            })
    
    if not questions_list:
        return None
    
    # Build prompt for LLM matching
    questions_text = "\n".join([
        f"{q['number']}. {q['question']}" for q in questions_list
    ])
    
    prompt = f"""You are an Answer Matcher. Match the user's answer to the correct question.

OPEN QUESTIONS:
{questions_text}

USER ANSWER:
{user_msg}

Determine which question(s) the user is answering. If the answer applies to a specific question, return its number. If the answer applies to multiple questions, return all relevant numbers.

Output JSON format:
{{
  "question_numbers": [1, 2] or [1] if single question,
  "answer_text": "extracted or cleaned answer text"
}}

If the answer doesn't match any question, return {{"question_numbers": [], "answer_text": ""}}.
"""
    
    model = genai.GenerativeModel(model_name=MODEL_NAME)
    chat = model.start_chat()
    
    try:
        response = _call_api_with_retry(chat, prompt)
        response_text = response.text
        
        # Extract JSON from response
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        result = json.loads(response_text.strip())
        question_numbers = result.get("question_numbers", [])
        answer_text = result.get("answer_text", user_msg)
        
        if question_numbers:
            # Get question IDs from numbers
            question_id = None
            for q in questions_list:
                if q["number"] in question_numbers:
                    question_id = q["id"]
                    break
            
            if question_id:
                return {
                    "question_id": question_id,
                    "answer": answer_text
                }
    except Exception as e:
        print(f"LLM matching error: {e}, falling back to simple matching")
    
    return None

def answer_parser_node(state: SharedState) -> SharedState:
    """
    Answer Parser Node - parses user answers and updates questions.md.
    """
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    current_phase = state.get('phase', 'INTAKE')
    
    if not feature_name:
        return handle_error_with_retry_budget(
            state,
            "answer_parser",
            "No feature_name in state."
        )
    
    print(f"[Answer Parser] Parsing answers for feature: {feature_name} (phase: {current_phase})")
    
    # Get user message
    user_msg = _get_last_user_message(state.get('messages', []))
    if not user_msg:
        return handle_error_with_retry_budget(
            state,
            "answer_parser",
            "No user message found in state.",
            context={"feature_name": feature_name}
        )
    
    # Get open questions from state
    open_questions = state.get('open_questions', []).copy()
    
    # Read existing questions.md
    questions_content = read_spec_file(feature_name, 'questions', spec_path)
    
    if not open_questions:
        print("[Answer Parser] No open questions found")
        return {}
    
    # Parse answers
    answered_count = 0
    question_id_answer_map = {}
    
    # Try to extract question number first
    question_num = _parse_question_number(user_msg)
    
    if question_num and question_num <= len(open_questions):
        # Direct question number match
        open_questions_list = [q for q in open_questions if q.get("status") == "open"]
        if question_num <= len(open_questions_list):
            question_to_answer = open_questions_list[question_num - 1]
            question_id = question_to_answer.get("id")
            # Extract answer text (everything after the question reference)
            answer_text = user_msg
            # Try to extract answer after question number
            match = re.search(r'(?:#|question|q)\s*\d+\s*[:\.]?\s*(.+)', user_msg, re.IGNORECASE | re.DOTALL)
            if match:
                answer_text = match.group(1).strip()
            
            question_id_answer_map[question_id] = answer_text
            answered_count = 1
    else:
        # Use LLM to match answer to question
        match_result = _match_answer_to_question_with_llm(user_msg, open_questions)
        if match_result:
            question_id = match_result.get("question_id")
            answer_text = match_result.get("answer", user_msg)
            question_id_answer_map[question_id] = answer_text
            answered_count = 1
        else:
            # If LLM matching failed and no explicit question number, try to match to all open questions
            # This handles cases where user provides a general answer that might apply to multiple questions
            open_questions_list = [q for q in open_questions if q.get("status") == "open"]
            if len(open_questions_list) == 1:
                # If only one open question, assume answer is for it
                question_id = open_questions_list[0].get("id")
                question_id_answer_map[question_id] = user_msg
                answered_count = 1
    
    # Update open_questions in state
    updated_questions = []
    for q in open_questions:
        question_id = q.get("id")
        if question_id in question_id_answer_map:
            answer_question(open_questions, question_id, question_id_answer_map[question_id])
            updated_questions.append(q)
    
    if answered_count == 0:
        print("[Answer Parser] Could not match answer to any question")
        error_result = handle_error_with_retry_budget(
            state,
            "answer_parser",
            "Could not match answer to any open question",
            context={"feature_name": feature_name, "user_message": user_msg[:200]}
        )
        error_result["messages"] = ["Answer Parser: Could not match your answer to any question. Please specify question number (e.g., '#1: answer')"]
        return error_result
    
    # Update questions.md file
    if questions_content and updated_questions:
        # Parse questions.md and update answers
        lines = questions_content.split('\n')
        updated_lines = []
        current_question_num = 0
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this is a question header
            if re.match(r'^##\s+Question\s+(\d+):', line, re.IGNORECASE):
                current_question_num += 1
                # Find the corresponding question in updated_questions
                question_to_update = None
                for q in updated_questions:
                    # Try to match by index (simplified - assumes order matches)
                    # In a more robust implementation, we'd use question IDs stored in the file
                    pass
                
                updated_lines.append(line)
                i += 1
                
                # Look for Answer line in this question section
                in_question_section = True
                while i < len(lines) and in_question_section:
                    line = lines[i]
                    
                    # Check if we've reached the next question section
                    if re.match(r'^##\s+Question\s+', line, re.IGNORECASE):
                        in_question_section = False
                        break
                    
                    # Update Answer line if found
                    if re.match(r'^-\s*\*\*Answer\*\*:', line, re.IGNORECASE):
                        # Find answer for this question number
                        answer_for_this = None
                        for q_idx, q in enumerate(updated_questions, 1):
                            if current_question_num == q_idx:
                                answer_for_this = q.get("answer", "")
                                break
                        
                        if answer_for_this:
                            updated_lines.append(f"- **Answer**: {answer_for_this}")
                            # Skip the old answer line
                            i += 1
                            continue
                    
                    # Update Status line if found
                    if re.match(r'^-\s*\*\*Status\*\*:', line, re.IGNORECASE):
                        updated_lines.append("- **Status**: answered")
                        i += 1
                        continue
                    
                    updated_lines.append(line)
                    i += 1
                
                continue
            
            updated_lines.append(line)
            i += 1
        
        updated_content = '\n'.join(updated_lines)
        write_spec_file(feature_name, "questions", updated_content, spec_path)
        print(f"[Answer Parser] Updated questions.md with {answered_count} answer(s)")
    
    return {
        "open_questions": open_questions,
        "messages": [f"Answer Parser: Recorded {answered_count} answer(s). {len([q for q in open_questions if q.get('status') == 'open'])} question(s) still open."]
    }

def answer_parser_router(state: SharedState) -> str:
    """
    Router for answer parser - determines next step after parsing answers.
    """
    from orchestrator.state import all_questions_answered
    
    current_phase = state.get('phase', 'INTAKE')
    open_questions = state.get('open_questions', [])
    
    # Check if all questions are answered
    if all_questions_answered(open_questions):
        # All questions answered - proceed to spec_updater
        print(f"[Answer Parser Router] All questions answered. Proceeding to spec_updater.")
        return "spec_updater"
    
    # Still have open questions - wait for more answers
    print(f"[Answer Parser Router] Still have open questions. Waiting for more answers.")
    return "__end__"


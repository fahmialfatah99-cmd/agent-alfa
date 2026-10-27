use fancy_regex::Regex;
use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

#[derive(Debug, PartialEq, Clone)]
pub enum MathVal {
    Int(i64),
    Float(f64),
}

impl MathVal {
    pub fn to_f64(&self) -> f64 {
        match *self {
            MathVal::Int(i) => i as f64,
            MathVal::Float(f) => f,
        }
    }
}

impl<'py> IntoPyObject<'py> for MathVal {
    type Target = PyAny;
    type Output = Bound<'py, Self::Target>;
    type Error = PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        match self {
            MathVal::Int(i) => Ok(i.into_pyobject(py)?.into_any()),
            MathVal::Float(f) => Ok(f.into_pyobject(py)?.into_any()),
        }
    }
}

impl std::fmt::Display for MathVal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MathVal::Int(i) => write!(f, "{}", i),
            MathVal::Float(fl) => write!(f, "{}", fl),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
enum Token {
    Num(f64),
    Plus,
    Minus,
    Mul,
    Div,
    FloorDiv,
    Mod,
    LParen,
    RParen,
}

fn tokenize(expr: &str) -> Option<Vec<Token>> {
    let mut tokens = Vec::new();
    let chars: Vec<char> = expr.chars().collect();
    let mut i = 0;
    let n = chars.len();

    while i < n {
        let c = chars[i];
        if c.is_whitespace() {
            i += 1;
            continue;
        }

        if c.is_ascii_digit() || (c == '.' && i + 1 < n && chars[i + 1].is_ascii_digit()) {
            let start = i;
            let mut has_dot = c == '.';
            i += 1;
            while i < n {
                if chars[i].is_ascii_digit() {
                    i += 1;
                } else if chars[i] == '.' && !has_dot {
                    has_dot = true;
                    i += 1;
                } else {
                    break;
                }
            }
            let s: String = chars[start..i].iter().collect();
            let val = s.parse::<f64>().ok()?;
            tokens.push(Token::Num(val));
            continue;
        }

        match c {
            '+' => tokens.push(Token::Plus),
            '-' => tokens.push(Token::Minus),
            '*' => tokens.push(Token::Mul),
            '%' => tokens.push(Token::Mod),
            '(' => tokens.push(Token::LParen),
            ')' => tokens.push(Token::RParen),
            '/' => {
                if i + 1 < n && chars[i + 1] == '/' {
                    tokens.push(Token::FloorDiv);
                    i += 1;
                } else {
                    tokens.push(Token::Div);
                }
            }
            _ => return None, // Unsupported character
        }
        i += 1;
    }

    Some(tokens)
}

struct Parser<'a> {
    tokens: &'a [Token],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn new(tokens: &'a [Token]) -> Self {
        Self { tokens, pos: 0 }
    }

    fn peek(&self) -> Option<&Token> {
        self.tokens.get(self.pos)
    }

    fn next_token(&mut self) -> Option<&Token> {
        let tok = self.tokens.get(self.pos);
        if tok.is_some() {
            self.pos += 1;
        }
        tok
    }

    fn parse_expression(&mut self) -> Option<f64> {
        self.parse_add_sub()
    }

    fn parse_add_sub(&mut self) -> Option<f64> {
        let mut left = self.parse_mul_div()?;
        while let Some(tok) = self.peek() {
            match tok {
                Token::Plus => {
                    self.next_token();
                    let right = self.parse_mul_div()?;
                    left += right;
                }
                Token::Minus => {
                    self.next_token();
                    let right = self.parse_mul_div()?;
                    left -= right;
                }
                _ => break,
            }
        }
        Some(left)
    }

    fn parse_mul_div(&mut self) -> Option<f64> {
        let mut left = self.parse_unary()?;
        while let Some(tok) = self.peek() {
            match tok {
                Token::Mul => {
                    self.next_token();
                    let right = self.parse_unary()?;
                    left *= right;
                }
                Token::Div => {
                    self.next_token();
                    let right = self.parse_unary()?;
                    if right == 0.0 {
                        return None;
                    }
                    left /= right;
                }
                Token::FloorDiv => {
                    self.next_token();
                    let right = self.parse_unary()?;
                    if right == 0.0 {
                        return None;
                    }
                    left = (left / right).floor();
                }
                Token::Mod => {
                    self.next_token();
                    let right = self.parse_unary()?;
                    if right == 0.0 {
                        return None;
                    }
                    left %= right;
                }
                _ => break,
            }
        }
        Some(left)
    }

    fn parse_unary(&mut self) -> Option<f64> {
        if let Some(tok) = self.peek() {
            match tok {
                Token::Plus => {
                    self.next_token();
                    self.parse_unary()
                }
                Token::Minus => {
                    self.next_token();
                    let val = self.parse_unary()?;
                    Some(-val)
                }
                _ => self.parse_primary(),
            }
        } else {
            None
        }
    }

    fn parse_primary(&mut self) -> Option<f64> {
        match self.next_token()? {
            Token::Num(v) => Some(*v),
            Token::LParen => {
                let inner = self.parse_expression()?;
                match self.next_token()? {
                    Token::RParen => Some(inner),
                    _ => None,
                }
            }
            _ => None,
        }
    }
}

pub fn eval_math_str(expr: &str) -> Option<MathVal> {
    let trimmed = expr.trim();
    if trimmed.is_empty() {
        return None;
    }

    // Normalized replacements
    let normalized = trimmed
        .replace('x', "*")
        .replace('×', "*")
        .replace('÷', "/");

    // Allowed chars check: digits, operators, parentheses, dot, whitespace (matches Python AST whitelist)
    for c in normalized.chars() {
        if !(c.is_ascii_digit() || c.is_whitespace() || "+-*/().".contains(c)) {
            return None;
        }
    }

    let tokens = tokenize(&normalized)?;
    if tokens.is_empty() {
        return None;
    }

    let mut parser = Parser::new(&tokens);
    let val = parser.parse_expression()?;

    // Must consume all tokens
    if parser.pos != tokens.len() || !val.is_finite() {
        return None;
    }

    if val.fract() == 0.0 && val >= (i64::MIN as f64) && val <= (i64::MAX as f64) {
        Some(MathVal::Int(val as i64))
    } else {
        let rounded = (val * 10000.0).round() / 10000.0;
        if rounded.fract() == 0.0 && rounded >= (i64::MIN as f64) && rounded <= (i64::MAX as f64) {
            Some(MathVal::Int(rounded as i64))
        } else {
            Some(MathVal::Float(rounded))
        }
    }
}

static EQUATION_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?<![a-zA-Z0-9_])(\d+(?:\.\d+)?(?:\s*[+\-*/×÷]\s*\d+(?:\.\d+)?)+)\s*=\s*(\d+(?:\.\d+)?)(?![a-zA-Z0-9_])")
        .expect("Invalid equation regex")
});

#[pyfunction]
pub fn safe_ast_math_eval(expr: &str) -> Option<MathVal> {
    eval_math_str(expr)
}

#[pyfunction]
pub fn is_rust_accelerated() -> bool {
    true
}

#[pyfunction]
pub fn verify_arithmetic_equations_in_text<'py>(
    py: Python<'py>,
    text: &str,
) -> PyResult<(String, Bound<'py, PyList>)> {
    let findings_list = PyList::empty(py);
    if text.is_empty() {
        return Ok((text.to_string(), findings_list));
    }

    let mut last_end = 0;
    let mut result_text = String::with_capacity(text.len());

    let mut matches = Vec::new();
    for m in EQUATION_RE.find_iter(text) {
        if let Ok(mat) = m {
            matches.push(mat);
        }
    }

    for mat in matches {
        let full_match = mat.as_str();
        let match_start = mat.start();
        let match_end = mat.end();

        // Extract lhs and rhs from full_match
        if let Some(captures) = EQUATION_RE.captures(full_match).ok().flatten() {
            let lhs = captures.get(1).map(|m| m.as_str()).unwrap_or("");
            let rhs_str = captures.get(2).map(|m| m.as_str()).unwrap_or("");

            if let Some(actual) = eval_math_str(lhs) {
                let claimed = if rhs_str.contains('.') {
                    rhs_str.parse::<f64>().map(MathVal::Float).ok()
                } else {
                    rhs_str.parse::<i64>().map(MathVal::Int).ok()
                };

                if let Some(claimed_val) = claimed {
                    let is_valid = (actual.to_f64() - claimed_val.to_f64()).abs() < 1e-6;

                    let finding_dict = PyDict::new(py);
                    finding_dict.set_item("expression", lhs.trim())?;
                    finding_dict.set_item("claimed", claimed_val.into_pyobject(py)?)?;
                    finding_dict.set_item("actual", actual.clone().into_pyobject(py)?)?;
                    finding_dict.set_item("is_valid", is_valid)?;
                    findings_list.append(finding_dict)?;

                    result_text.push_str(&text[last_end..match_start]);
                    if is_valid {
                        result_text.push_str(full_match);
                    } else {
                        result_text.push_str(&format!("{} = {}", lhs, actual));
                    }
                    last_end = match_end;
                    continue;
                }
            }
        }

        // Default: keep match untouched
        result_text.push_str(&text[last_end..match_end]);
        last_end = match_end;
    }

    result_text.push_str(&text[last_end..]);
    Ok((result_text, findings_list))
}

#[inline]
pub fn calc_cosine_similarity(vec_a: &[f32], vec_b: &[f32]) -> f64 {
    if vec_a.is_empty() || vec_b.is_empty() {
        return 0.0;
    }

    let min_len = vec_a.len().min(vec_b.len());
    let mut dot = 0.0f64;
    for i in 0..min_len {
        dot += (vec_a[i] as f64) * (vec_b[i] as f64);
    }

    let mut sum_sq_a = 0.0f64;
    for &x in vec_a {
        let xf = x as f64;
        sum_sq_a += xf * xf;
    }
    let norm_a = sum_sq_a.sqrt();

    let mut sum_sq_b = 0.0f64;
    for &y in vec_b {
        let yf = y as f64;
        sum_sq_b += yf * yf;
    }
    let norm_b = sum_sq_b.sqrt();

    if norm_a < 1e-6 || norm_b < 1e-6 {
        return 0.0;
    }

    dot / (norm_a * norm_b)
}

#[pyfunction]
pub fn cosine_similarity(vec_a: Vec<f32>, vec_b: Vec<f32>) -> f64 {
    calc_cosine_similarity(&vec_a, &vec_b)
}

#[pyfunction]
pub fn batch_cosine_similarity(query: Vec<f32>, vectors: Vec<Vec<f32>>) -> Vec<f64> {
    if query.is_empty() {
        return vec![0.0; vectors.len()];
    }

    let mut sum_sq_q = 0.0f64;
    for &x in &query {
        let xf = x as f64;
        sum_sq_q += xf * xf;
    }
    let norm_q = sum_sq_q.sqrt();
    if norm_q < 1e-6 {
        return vec![0.0; vectors.len()];
    }

    let q_len = query.len();
    let mut results = Vec::with_capacity(vectors.len());

    for vec_b in &vectors {
        if vec_b.is_empty() {
            results.push(0.0);
            continue;
        }

        let min_len = q_len.min(vec_b.len());
        let mut dot = 0.0f64;
        for i in 0..min_len {
            dot += (query[i] as f64) * (vec_b[i] as f64);
        }

        let mut sum_sq_b = 0.0f64;
        for &y in vec_b {
            let yf = y as f64;
            sum_sq_b += yf * yf;
        }
        let norm_b = sum_sq_b.sqrt();

        if norm_b < 1e-6 {
            results.push(0.0);
        } else {
            results.push(dot / (norm_q * norm_b));
        }
    }

    results
}

static FASTPATH_REGEX_CACHE: LazyLock<Mutex<HashMap<String, Option<Regex>>>> = LazyLock::new(|| {
    Mutex::new(HashMap::new())
});

pub fn get_or_compile_fastpath_regex(pattern: &str) -> Option<Regex> {
    let mut cache = FASTPATH_REGEX_CACHE.lock().unwrap();
    if let Some(opt_re) = cache.get(pattern) {
        return opt_re.clone();
    }

    let wrapped = if pattern.starts_with('^') {
        format!("(?i){}", pattern)
    } else {
        format!("(?i)\\A(?:{})", pattern)
    };

    let compiled = Regex::new(&wrapped).ok();
    cache.insert(pattern.to_string(), compiled.clone());
    compiled
}

#[pyfunction]
pub fn match_fastpath_pattern(prompt: &str, pattern: &str) -> bool {
    if let Some(re) = get_or_compile_fastpath_regex(pattern) {
        re.is_match(prompt).unwrap_or(false)
    } else {
        false
    }
}

#[pyfunction]
pub fn find_matching_fastpath_id(prompt: &str, candidates: Vec<(i64, String)>) -> Option<i64> {
    for (id, pattern) in candidates {
        if match_fastpath_pattern(prompt, &pattern) {
            return Some(id);
        }
    }
    None
}

#[pyclass]
pub struct FastPathEngine {
    patterns: Vec<(i64, Regex)>,
}

#[pymethods]
impl FastPathEngine {
    #[new]
    pub fn new() -> Self {
        Self {
            patterns: Vec::new(),
        }
    }

    pub fn set_patterns(&mut self, list: Vec<(i64, String)>) {
        self.patterns.clear();
        for (id, pat) in list {
            let wrapped = if pat.starts_with('^') {
                format!("(?i){}", pat)
            } else {
                format!("(?i)\\A(?:{})", pat)
            };
            if let Ok(re) = Regex::new(&wrapped) {
                self.patterns.push((id, re));
            }
        }
    }

    pub fn find_match(&self, prompt: &str) -> Option<i64> {
        for (id, re) in &self.patterns {
            if re.is_match(prompt).unwrap_or(false) {
                return Some(*id);
            }
        }
        None
    }
}

pub fn tokenize_for_bm25(text: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    let n = chars.len();

    while i < n {
        while i < n && !(chars[i].is_alphanumeric() || chars[i] == '_') {
            i += 1;
        }
        if i >= n {
            break;
        }
        let start = i;
        while i < n && (chars[i].is_alphanumeric() || chars[i] == '_') {
            i += 1;
        }
        if i - start > 1 {
            let word = chars[start..i].iter().collect::<String>().to_lowercase();
            tokens.push(word);
        }
    }
    tokens
}

#[pyfunction]
pub fn calculate_bm25_scores(corpus: Vec<String>, query: String) -> Vec<f64> {
    let n_docs = corpus.len();
    if n_docs == 0 || query.trim().is_empty() {
        return vec![0.0; n_docs];
    }

    let q_tokens = tokenize_for_bm25(&query);
    if q_tokens.is_empty() {
        return vec![0.0; n_docs];
    }

    let mut doc_tokens_list: Vec<Vec<String>> = Vec::with_capacity(n_docs);
    let mut doc_lens = Vec::with_capacity(n_docs);
    let mut total_tokens = 0usize;

    for text in &corpus {
        let tokens = tokenize_for_bm25(text);
        let len = tokens.len();
        doc_lens.push(len);
        total_tokens += len;
        doc_tokens_list.push(tokens);
    }

    if total_tokens == 0 {
        return vec![0.0; n_docs];
    }

    let avgdl = (total_tokens as f64) / (n_docs as f64);

    let mut doc_freqs: Vec<HashMap<String, u32>> = Vec::with_capacity(n_docs);
    let mut nd: HashMap<String, u32> = HashMap::new();

    for doc_tokens in doc_tokens_list {
        let mut freqs: HashMap<String, u32> = HashMap::new();
        for token in doc_tokens {
            *freqs.entry(token).or_insert(0) += 1;
        }
        for word in freqs.keys() {
            *nd.entry(word.clone()).or_insert(0) += 1;
        }
        doc_freqs.push(freqs);
    }

    let n_f64 = n_docs as f64;
    let mut idf_map: HashMap<String, f64> = HashMap::new();
    let mut idf_sum = 0.0f64;
    let mut negative_idfs: Vec<String> = Vec::new();

    for (word, &df) in &nd {
        let df_f64 = df as f64;
        let idf = ((n_f64 - df_f64 + 0.5) / (df_f64 + 0.5)).ln();
        idf_map.insert(word.clone(), idf);
        idf_sum += idf;
        if idf < 0.0 {
            negative_idfs.push(word.clone());
        }
    }

    let avg_idf = if !idf_map.is_empty() {
        idf_sum / (idf_map.len() as f64)
    } else {
        0.0
    };

    let eps = 0.25f64 * avg_idf;
    for word in negative_idfs {
        idf_map.insert(word, eps);
    }

    let k1 = 1.5f64;
    let b = 0.75f64;
    let mut scores = vec![0.0f64; n_docs];

    for q in &q_tokens {
        if let Some(&q_idf) = idf_map.get(q) {
            for d in 0..n_docs {
                let q_freq = doc_freqs[d].get(q).copied().unwrap_or(0) as f64;
                if q_freq > 0.0 {
                    let d_len = doc_lens[d] as f64;
                    let denom = q_freq + k1 * (1.0 - b + b * (d_len / avgdl));
                    scores[d] += q_idf * (q_freq * (k1 + 1.0) / denom);
                }
            }
        }
    }

    let mut max_s = 0.0f64;
    for &s in &scores {
        if s > max_s {
            max_s = s;
        }
    }

    if max_s > 0.0 {
        scores.into_iter().map(|s| (s / max_s).max(0.0)).collect()
    } else {
        vec![0.0; n_docs]
    }
}

#[pyfunction]
pub fn find_seed_entity_indices(
    tokens: Vec<String>,
    entity_names: Vec<String>,
    limit: usize,
) -> Vec<usize> {
    let mut matched_indices = Vec::new();
    let mut seen_names = std::collections::HashSet::new();

    for (idx, name) in entity_names.iter().enumerate() {
        let name_upper = name.to_uppercase();
        for tok in &tokens {
            if name_upper.contains(tok) {
                if seen_names.insert(name.clone()) {
                    matched_indices.push(idx);
                    if matched_indices.len() >= limit {
                        return matched_indices;
                    }
                }
                break;
            }
        }
    }
    matched_indices
}

#[pyfunction]
pub fn filter_hop2_bridges(
    hop1_keys: Vec<(String, String, String)>,
    candidate_edges: Vec<(String, String, String)>,
    limit: usize,
) -> Vec<usize> {
    let mut hop1_set: std::collections::HashSet<(String, String, String)> =
        std::collections::HashSet::from_iter(hop1_keys);

    let mut result_indices = Vec::new();
    for (idx, edge) in candidate_edges.iter().enumerate() {
        if !hop1_set.contains(edge) {
            hop1_set.insert(edge.clone());
            result_indices.push(idx);
            if result_indices.len() >= limit {
                break;
            }
        }
    }
    result_indices
}

#[pyfunction]
pub fn batch_cosine_from_json_strings(query: Vec<f32>, json_strings: Vec<String>) -> Vec<f64> {
    if query.is_empty() {
        return vec![0.0; json_strings.len()];
    }

    let mut sum_sq_q = 0.0f64;
    for &x in &query {
        let xf = x as f64;
        sum_sq_q += xf * xf;
    }
    let norm_q = sum_sq_q.sqrt();
    if norm_q < 1e-6 {
        return vec![0.0; json_strings.len()];
    }

    let q_len = query.len();
    let mut results = Vec::with_capacity(json_strings.len());

    for json_str in &json_strings {
        if let Ok(vec_b) = serde_json::from_str::<Vec<f32>>(json_str) {
            if vec_b.is_empty() {
                results.push(0.0);
                continue;
            }
            let min_len = q_len.min(vec_b.len());
            let mut dot = 0.0f64;
            for i in 0..min_len {
                dot += (query[i] as f64) * (vec_b[i] as f64);
            }
            let mut sum_sq_b = 0.0f64;
            for &y in &vec_b {
                let yf = y as f64;
                sum_sq_b += yf * yf;
            }
            let norm_b = sum_sq_b.sqrt();
            if norm_b < 1e-6 {
                results.push(0.0);
            } else {
                results.push(dot / (norm_q * norm_b));
            }
        } else {
            results.push(0.0);
        }
    }

    results
}

static CPU_STAT_PREV: LazyLock<Mutex<(u64, u64)>> = LazyLock::new(|| {
    Mutex::new((0, 0))
});

pub fn read_linux_cpu_percent() -> f64 {
    if let Ok(stat) = std::fs::read_to_string("/proc/stat") {
        if let Some(first_line) = stat.lines().next() {
            let parts: Vec<&str> = first_line.split_whitespace().collect();
            if parts.len() >= 5 && parts[0] == "cpu" {
                let user: u64 = parts[1].parse().unwrap_or(0);
                let nice: u64 = parts[2].parse().unwrap_or(0);
                let system: u64 = parts[3].parse().unwrap_or(0);
                let idle: u64 = parts[4].parse().unwrap_or(0);
                let iowait: u64 = parts.get(5).and_then(|s| s.parse().ok()).unwrap_or(0);
                let irq: u64 = parts.get(6).and_then(|s| s.parse().ok()).unwrap_or(0);
                let softirq: u64 = parts.get(7).and_then(|s| s.parse().ok()).unwrap_or(0);
                let steal: u64 = parts.get(8).and_then(|s| s.parse().ok()).unwrap_or(0);

                let total = user + nice + system + idle + iowait + irq + softirq + steal;
                let idle_time = idle + iowait;

                let mut prev = CPU_STAT_PREV.lock().unwrap();
                let (prev_idle, prev_total) = *prev;
                *prev = (idle_time, total);

                if prev_total > 0 && total > prev_total {
                    let diff_total = total - prev_total;
                    let diff_idle = idle_time.saturating_sub(prev_idle);
                    let usage = (1.0 - (diff_idle as f64) / (diff_total as f64)) * 100.0;
                    return usage.clamp(0.0, 100.0);
                }
            }
        }
    }
    10.0
}

pub fn read_linux_memory() -> (f64, f64) {
    let mut total_kb = 0.0f64;
    let mut avail_kb = 0.0f64;

    if let Ok(meminfo) = std::fs::read_to_string("/proc/meminfo") {
        for line in meminfo.lines() {
            if line.starts_with("MemTotal:") {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 2 {
                    total_kb = parts[1].parse().unwrap_or(0.0);
                }
            } else if line.starts_with("MemAvailable:") {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 2 {
                    avail_kb = parts[1].parse().unwrap_or(0.0);
                }
            }
            if total_kb > 0.0 && avail_kb > 0.0 {
                break;
            }
        }
    }

    if total_kb > 0.0 {
        let used_pct = ((total_kb - avail_kb) / total_kb) * 100.0;
        let avail_mb = avail_kb / 1024.0;
        (used_pct.clamp(0.0, 100.0), avail_mb)
    } else {
        (50.0, 2048.0)
    }
}

pub fn read_linux_cpu_temp() -> f64 {
    let mut max_temp = 0.0f64;
    if let Ok(entries) = std::fs::read_dir("/sys/class/thermal") {
        for entry in entries.flatten() {
            let path = entry.path().join("temp");
            if let Ok(content) = std::fs::read_to_string(&path) {
                if let Ok(raw) = content.trim().parse::<f64>() {
                    let val = raw / 1000.0;
                    if val > 15.0 && val < 115.0 && val > max_temp {
                        max_temp = val;
                    }
                }
            }
        }
    }
    if max_temp > 0.0 {
        (max_temp * 10.0).round() / 10.0
    } else {
        45.0
    }
}

#[pyfunction]
pub fn read_host_hardware_telemetry() -> (f64, f64, f64, f64) {
    let cpu_pct = read_linux_cpu_percent();
    let (ram_pct, ram_avail_mb) = read_linux_memory();
    let temp_c = read_linux_cpu_temp();
    (cpu_pct, ram_pct, ram_avail_mb, temp_c)
}

#[pymodule]
fn alfa_accel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<FastPathEngine>()?;
    m.add_function(wrap_pyfunction!(is_rust_accelerated, m)?)?;
    m.add_function(wrap_pyfunction!(safe_ast_math_eval, m)?)?;
    m.add_function(wrap_pyfunction!(verify_arithmetic_equations_in_text, m)?)?;
    m.add_function(wrap_pyfunction!(cosine_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(batch_cosine_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(batch_cosine_from_json_strings, m)?)?;
    m.add_function(wrap_pyfunction!(match_fastpath_pattern, m)?)?;
    m.add_function(wrap_pyfunction!(find_matching_fastpath_id, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_bm25_scores, m)?)?;
    m.add_function(wrap_pyfunction!(find_seed_entity_indices, m)?)?;
    m.add_function(wrap_pyfunction!(filter_hop2_bridges, m)?)?;
    m.add_function(wrap_pyfunction!(read_host_hardware_telemetry, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cosine_similarity() {
        let a = vec![1.0, 0.0, 0.0];
        let b = vec![1.0, 0.0, 0.0, 0.0, 0.0];
        let sim = calc_cosine_similarity(&a, &b);
        assert!((sim - 1.0).abs() < 1e-6);

        let empty: Vec<f32> = vec![];
        assert_eq!(calc_cosine_similarity(&empty, &a), 0.0);
        assert_eq!(calc_cosine_similarity(&vec![0.0, 0.0], &vec![0.0, 0.0]), 0.0);

        let c = vec![0.0, 1.0, 0.0];
        assert!((calc_cosine_similarity(&a, &c)).abs() < 1e-6);
    }

    #[test]
    fn test_eval_basic() {
        assert_eq!(eval_math_str("68 - 7"), Some(MathVal::Int(61)));
        assert_eq!(eval_math_str("63 + 94 + 1 + 2"), Some(MathVal::Int(160)));
        assert_eq!(eval_math_str("(68 - 7) + 99"), Some(MathVal::Int(160)));
        assert_eq!(eval_math_str("10 / 2"), Some(MathVal::Int(5)));
        assert_eq!(eval_math_str("10 / 4"), Some(MathVal::Float(2.5)));
        assert_eq!(eval_math_str("10 // 4"), Some(MathVal::Int(2)));
    }

    #[test]
    fn test_eval_unsafe() {
        assert_eq!(eval_math_str("__import__('os').system('ls')"), None);
        assert_eq!(eval_math_str("import sys"), None);
        assert_eq!(eval_math_str("10 / 0"), None);
        assert_eq!(eval_math_str(""), None);
    }

    #[test]
    fn test_equation_regex_capture() {
        let text = "Mandor Mugi mengambil 68 - 7 = 64 batang dan total 61 + 99 = 170 batang.";
        let matches: Vec<_> = EQUATION_RE.find_iter(text).filter_map(|m| m.ok()).collect();
        assert_eq!(matches.len(), 2);
    }

    #[test]
    fn test_fastpath_pattern_matching() {
        let pattern = r"^\s*(?:berapa|cek|info|total|rekap)?\s*(?:jumlah\s+|total\s+)?tiang\s+(?:bersih\s+|net\s+)?(?:cluster\s+)?lahat\s*\??\s*$";
        assert!(match_fastpath_pattern("berapa total tiang bersih lahat?", pattern));
        assert!(match_fastpath_pattern("total tiang lahat", pattern));
        assert!(!match_fastpath_pattern("salah bukan begitu total tiang", pattern));

        let candidates = vec![
            (10, r"^\s*halo\s*$".to_string()),
            (20, pattern.to_string()),
        ];
        assert_eq!(find_matching_fastpath_id("berapa total tiang bersih lahat?", candidates.clone()), Some(20));
        assert_eq!(find_matching_fastpath_id("halo", candidates.clone()), Some(10));
        assert_eq!(find_matching_fastpath_id("selamat pagi", candidates), None);
    }

    #[test]
    fn test_bm25_scoring() {
        let corpus = vec![
            "Python programming and backend development".to_string(),
            "Rust programming with fearless concurrency and memory safety".to_string(),
            "Baking delicious chocolate cakes and sweet pastries".to_string(),
        ];
        let query = "Rust programming safety".to_string();
        let scores = calculate_bm25_scores(corpus, query);
        assert_eq!(scores.len(), 3);
        assert_eq!(scores[1], 1.0); // Best match should be normalized to 1.0
        assert!(scores[0] > 0.0);   // Matches 'programming'
        assert_eq!(scores[2], 0.0); // No matching tokens
    }

    #[test]
    fn test_graph_helpers() {
        let names = vec![
            "PROJECT_ORION".to_string(),
            "TELEGRAM_BOT".to_string(),
            "ORION_DB".to_string(),
            "RUST_ENGINE".to_string(),
        ];
        let tokens = vec!["ORION".to_string()];
        let indices = find_seed_entity_indices(tokens, names, 10);
        assert_eq!(indices, vec![0, 2]);

        let hop1 = vec![("A".to_string(), "REL".to_string(), "B".to_string())];
        let candidates = vec![
            ("A".to_string(), "REL".to_string(), "B".to_string()),
            ("B".to_string(), "REL".to_string(), "C".to_string()),
        ];
        let res = filter_hop2_bridges(hop1, candidates, 5);
        assert_eq!(res, vec![1]);
    }

    #[test]
    fn test_batch_cosine_from_json_strings() {
        let q = vec![1.0, 0.0, 0.0];
        let jsons = vec![
            "[1.0, 0.0, 0.0]".to_string(),
            "[0.0, 1.0, 0.0]".to_string(),
            "[-1.0, 0.0, 0.0]".to_string(),
            "invalid_json".to_string(),
        ];
        let sims = batch_cosine_from_json_strings(q, jsons);
        assert_eq!(sims.len(), 4);
        assert!((sims[0] - 1.0).abs() < 1e-5);
        assert!((sims[1] - 0.0).abs() < 1e-5);
        assert!((sims[2] - (-1.0)).abs() < 1e-5);
        assert_eq!(sims[3], 0.0);
    }

    #[test]
    fn test_host_hardware_telemetry() {
        let (cpu, ram, avail, temp) = read_host_hardware_telemetry();
        assert!(cpu >= 0.0 && cpu <= 100.0);
        assert!(ram >= 0.0 && ram <= 100.0);
        assert!(avail >= 0.0);
        assert!(temp >= 15.0 && temp <= 115.0);
    }
}


def _remove_optimise_colopro_calls(script: str) -> str:
    """
    Remove optimise_colopro calls and replace with assignment to dag_sink.

    Transforms:
        outcomes = optimise_colopro(dag_sink=pipeline, ...)
    To:
        outcomes = pipeline
    """
    lines = script.split('\n')
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.search(r"^(\s*)(\w+)\s*=\s*optimise_colopro\s*\(", line)
        if match:
             indent = match.group(1)
             var_name = match.group(2)
             
             # Collect lines until end of call
             collected = ""
             nesting = 0
             start_i = i
             
             while i < len(lines):
                  l = lines[i]
                  collected += l + "\n"
                  nesting += l.count('(') - l.count(')')
                  if nesting <= 0 and l.strip(): # Check if we closed all parens
                      i += 1
                      break
                  i += 1
             
             # Search for dag_sink
             dag_sink_var = "None"
             sink_match = re.search(r"dag_sink\s*=\s*([a-zA-Z_][a-zA-Z0-9_]*)", collected)
             if sink_match:
                 dag_sink_var = sink_match.group(1)
             else:
                 # Check first arg
                 parts = collected.split('optimise_colopro', 1)
                 if len(parts) > 1:
                     after = parts[1].strip()
                     if after.startswith('('):
                         inner = after[1:]
                         first = inner.split(',', 1)[0].strip()
                         if first and first.isidentifier():
                             dag_sink_var = first
             
             new_lines.append(f"{indent}{var_name} = {dag_sink_var}  # optimise_colopro stripped")
             continue

        new_lines.append(line)
        i += 1
        
    return '\n'.join(new_lines)

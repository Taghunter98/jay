import re
import os
import sys
import subprocess

class ScopeStack:
    def __init__(self):
        self.stack = [{}]
    def enter_scope(self):
        self.stack.append({})
    def exit_scope(self):
        self.stack.pop()
    def declare_var(self, name, typ):
        self.stack[-1][name] = typ
    def lookup_var(self, name):
        for scope in reversed(self.stack):
            if name in scope:
                return scope[name]
        return None

def jay_type_to_rust(jay_type):
    return {"int": "i32", "string": "String", "bool": "bool"}.get(jay_type.lower(), "String")

def extract_func_signature(header):
    # func add(a: int, b: int) -> int {
    name = header.split()[1].split("(")[0]
    params_str = header.split("(", 1)[1].split(")", 1)[0]
    params = []
    if params_str.strip():
        for p in params_str.split(","):
            pname, ptype = p.strip().split(":")
            pname, ptype = pname.strip(), ptype.strip()
            params.append((pname, jay_type_to_rust(ptype)))
    ret_type = "()"
    if "->" in header:
        ret_type = jay_type_to_rust(header.split("->")[1].split("{")[0].strip())
    return name, params, ret_type

def build_function_table(lines):
    func_table = {}
    i = 0
    while i < len(lines):
        if lines[i].startswith("func "):
            header = lines[i]
            name, params, ret_type = extract_func_signature(header)
            func_table[name] = {"params": params, "ret_type": ret_type}
            # Skip to end of function
            while i < len(lines) and not lines[i].startswith("}"):
                i += 1
        i += 1
    return func_table

def compile_jay_func(lines, scope, func_table):
    header = lines[0]
    name, params, ret_type = extract_func_signature(header)
    body = []
    scope.enter_scope()
    for pname, ptype in params:
        scope.declare_var(pname, ptype)
    for line in lines[1:-1]:
        line = line.rstrip(';').strip()
        if line.startswith("let "):
            # let var: type = expr
            _, rest = line.split("let ", 1)
            if ":" in rest:
                left, right = rest.split("=")
                vname, vtype = left.strip().split(":")
                vname, vtype = vname.strip(), jay_type_to_rust(vtype.strip())
                scope.declare_var(vname, vtype)
                right = right.strip()
            else:
                # type inference: let res = add(a, b)
                vname, right = rest.split("=")
                vname = vname.strip()
                right = right.strip()
                # Try to infer type if this is a function call
                m = re.match(r"(\w+)\((.*)\)", right)
                if m:
                    func = m.group(1)
                    if func in func_table:
                        vtype = func_table[func]['ret_type']
                    else:
                        vtype = "i32" # default fallback
                else:
                    vtype = "i32"
                scope.declare_var(vname, vtype)
            # Handle function calls in right-hand side
            if re.match(r"\w+\(.*\)", right):
                body.append(f"    let {vname}: {vtype} = {right};")
            elif vtype == "String":
                if not right.startswith('"'):
                    right = f'"{right}"'
                right = f"{right}.to_string()"
                body.append(f"    let {vname}: {vtype} = {right};")
            else:
                body.append(f"    let {vname}: {vtype} = {right};")
        elif line.startswith("return "):
            expr = line[len("return "):].strip()
            body.append(f"    return {expr};")
        elif line.startswith("print("):
            inner = line[len("print("):-1]
            vtype = scope.lookup_var(inner)
            if vtype == "String":
                body.append(f"    println!(\"{{}}\", {inner}.as_str());")
            else:
                body.append(f"    println!(\"{{}}\", {inner});")
        elif re.match(r"\w+\(.*\)", line):
            # Handle standalone function calls like add(a, b)
            body.append(f"    {line};")
    scope.exit_scope()
    params_rust = ", ".join(f"{n}: {t}" for n, t in params)
    return f"pub fn {name}({params_rust}) -> {ret_type} {{\n" + "\n".join(body) + "\n}"

def parse_and_compile_jay(jay_code):
    lines = [l.strip() for l in jay_code.splitlines() if l.strip()]
    func_table = build_function_table(lines)
    i = 0
    rust_fns = []
    scope = ScopeStack()
    while i < len(lines):
        if lines[i].startswith("func "):
            func_lines = [lines[i]]
            i += 1
            while i < len(lines) and not lines[i].startswith("}"):
                func_lines.append(lines[i])
                i += 1
            func_lines.append("}")
            header = func_lines[0]
            name, params, ret_type = extract_func_signature(header)
            
            if name == "main":
                rust_fns.append(compile_jay_func(func_lines, scope, func_table).replace("pub fn main", "fn main"))
            else:
                rust_fns.append(compile_jay_func(func_lines, scope, func_table))
        i += 1

    return "\n\n".join(rust_fns)

def write_rust_file(rust_code, directory="jay_out"):
    os.makedirs(directory + "/src", exist_ok=True)
    main_path = os.path.join(directory, "src", "main.rs")
    with open(main_path, "w") as f:
        f.write(rust_code)
    print(f"Rust code written to {main_path}")

def write_cargo_toml(directory="jay_out"):
    cargo_toml = """[package]
name = "jay_out"
version = "0.1.0"
edition = "2021"

[dependencies]
"""
    with open(os.path.join(directory, "Cargo.toml"), "w") as f:
        f.write(cargo_toml)
    print(f"Cargo.toml written to {directory}/Cargo.toml")

def build_and_run(directory="jay_out"):
    print("Compiling with cargo...")
    try:
        subprocess.run(["cargo", "build"], cwd=directory, check=True)
        print("Running the executable:")
        subprocess.run(["cargo", "run"], cwd=directory, check=True)
    except subprocess.CalledProcessError:
        print("Compilation or execution failed.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python jay_to_rust_functional.py input.jay")
        sys.exit(1)
    jay_file = sys.argv[1]
    with open(jay_file, "r") as f:
        jay_code = f.read()
    rust_code = parse_and_compile_jay(jay_code)
    write_rust_file(rust_code)
    write_cargo_toml()
    build_and_run()
	

"""
Jay Compiler Prototype

TODO
- string concatentation
- Comment support
- control statements

"""

import re
import os
import sys
import subprocess


class ScopeStack:
    """
    Stack implementation for the scope of the Jay file.

    Stores the current variables in the stack with functions to lookup and type check values in scope.
    """

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


def jay_type_to_rust(jay_type: str) -> str:
    """
    Returns the Rust type from Jay type.

    Args:
        jay_type (string): Jay variable type (int, string, bool)

    Returns:
        string: Rust type
    """
    return {"int": "i32", "string": "String", "bool": "bool"}.get(
        jay_type.lower(), "String"
    )


def extract_func_signature(header: str) -> any:
    """
    Function extracts the signature of the Jay function and returns the name, parameters and return type.

    Args:
        header (string): Jay function header -> func my_func(val: int, val2: str) -> string

    Returns:
        string: Name, parameters and return type
    """

    # Get the header values by splitting the header into func <name> (<params_str>) -> <ret_type>
    name: str = header.split()[1].split("(")[0]
    params_str: str = header.split("(", 1)[1].split(")", 1)[0]
    params: list = []

    if params_str.strip():
        for p in params_str.split(","):
            pname, ptype = p.strip().split(":")
            pname, ptype = pname.strip(), ptype.strip()
            params.append((pname, jay_type_to_rust(ptype)))

    ret_type: str = "()"

    # Look for the return type based on arrow
    if "->" in header:
        ret_type = jay_type_to_rust(header.split("->")[1].split("{")[0].strip())
    return name, params, ret_type


def build_function_table(lines: str) -> dict:
    """
    Builds a function table to store the functions within the file's scope.

    Function creates a new dict to store functions, then for each function, based on the func keyword to the '}' end of the function,
    the program extracts the function header and stores them in the table.

    The value i is incremented for each line as to ensure that only the functions are extracted.

    Args:
        lines (string): Jay code

    Returns:
        dict: function table
    """
    func_table: dict = {}

    i = 0  # Value to keep track of lines parsed

    while i < len(lines):
        if lines[i].startswith("func "):
            header: str = lines[i]
            name, params, ret_type = extract_func_signature(header)
            func_table[name] = {"params": params, "ret_type": ret_type}

            while i < len(lines) and not lines[i].startswith("}"):
                i += 1
        i += 1

    return func_table


def compile_jay_func(lines: str, scope: ScopeStack, func_table: dict) -> str:
    """
    The function compiles a Jay function into a valid Rust function.

    Args:
        lines (str): Jay code
        scope (ScopeStack): The Scope stack
        func_table (dict): The function table - ensures functions can be called

    Returns:
        str: Generated Rust function code
    """

    header = lines[0]
    name, params, ret_type = extract_func_signature(header)
    body = []

    scope.enter_scope()

    for pname, ptype in params:
        scope.declare_var(pname, ptype)

    for line in lines[1:-1]:
        line = line.rstrip(";").strip()

        if line.startswith("let "):
            # Expressions
            _, rest = line.split("let ", 1)

            if ":" in rest:
                left, right = rest.split("=")
                vname, vtype = left.strip().split(":")
                vname, vtype = vname.strip(), jay_type_to_rust(vtype.strip())

                scope.declare_var(vname, vtype)

                right = right.strip()

            # Function calls
            if re.match(r"\w+\(.*\)", right):
                body.append(f"    let {vname}: {vtype} = {right};")

            # String types
            elif vtype == "String":
                if not right.startswith('"'):
                    right = f'"{right}"'

                # String concatenation 
                if "+" in right:
                    operands = [op.strip() for op in re.split(r'\+', right)]
                    fmt = '"' + '{}'*len(operands) + '"'
                    args = ', '.join(operands)
                    right = f'format!({fmt}, {args})'
                else:
                    right = f"{right}.to_string()"

                body.append(f"    let {vname}: {vtype} = {right};")

            else:
                body.append(f"    let {vname}: {vtype} = {right};")

        # Return
        elif line.startswith("return "):
            expr = line[len("return ") :].strip()
            body.append(f"    return {expr};")

        # Print statement
        elif line.startswith("print("):
            inner = line[len("print(") : -1]
            vtype = scope.lookup_var(inner)

            if vtype == "String":
                body.append(f'    println!("{{}}", {inner}.as_str());')
            else:
                body.append(f'    println!("{{}}", {inner});')

        # Standalone function calls
        elif re.match(r"\w+\(.*\)", line):
            body.append(f"    {line};")

            
    scope.exit_scope()

    params_rust = ", ".join(f"{n}: {t}" for n, t in params)

    return f"pub fn {name}({params_rust}) -> {ret_type} {{\n" + "\n".join(body) + "\n}"


def parse_and_compile_jay(jay_code: str):
    """
    Function parses and compiles Jay code into Rust, creates the Scope Stack and Function table then returns Rust code.

    Args:
        jay_code (str): Jay code

    Returns:
        str: Rust code
    """

    lines = [l.strip() for l in jay_code.splitlines() if l.strip()]
    func_table = build_function_table(lines)
    i = 0
    rust_fns = []

    scope = ScopeStack()

    while i < len(lines):
        # Parse a function based on 'func' keyword
        if lines[i].startswith("func "):
            func_lines = [lines[i]]
            i += 1

            # Move through lines until '}' signifying end of function
            while i < len(lines) and not lines[i].startswith("}"):
                func_lines.append(lines[i])
                i += 1

            func_lines.append("}")
            header = func_lines[0]
            name, params, ret_type = extract_func_signature(header)

            # Special main case - main point of entry for both Rust and Jay
            if name == "main":
                rust_fns.append(
                    compile_jay_func(func_lines, scope, func_table).replace(
                        "pub fn main", "fn main"
                    )
                )
            else:
                rust_fns.append(compile_jay_func(func_lines, scope, func_table))

        i += 1

    return "\n\n".join(rust_fns)


def write_rust_file(rust_code: str, directory="jay_out"):
    """
    Creates a Rust file in the jay-out directory.

    Args:
        rust_code (str): Rust code to be written
        directory (str, optional): Output directory. Defaults to "jay_out".
    """
    os.makedirs(directory + "/src", exist_ok=True)

    main_path = os.path.join(directory, "src", "main.rs")

    with open(main_path, "w") as f:
        f.write(rust_code)

    print(f"Rust code written to {main_path}")


def write_cargo_toml(directory="jay_out"):
    """
    Creates a Cargo.toml file to be able to execute Rust code.

    Args:
        directory (str, optional): Output directory. Defaults to "jay_out".
    """
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
    """
    Main build and run function for Jay, function builds the Rust code and executes with cargo.

    Args:
        directory (str, optional): Output directory. Defaults to "jay_out".
    """
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

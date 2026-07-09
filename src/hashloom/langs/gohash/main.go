// Command gohash prints the sha256 of a Go definition's normalised AST.
//
// Usage: gohash <file.go> <Qualname>
//
// Qualname is a top-level func or type name, or "Type.method" for a method.
// The dump drops source positions and comment/doc groups, so formatting,
// comment, and doc-comment edits never change the hash, but a signature or body
// change does. This is the Go analogue of hashloom's Python ast.dump hash.
//
// The result is one line on stdout, exit 0, so it survives `go run` (which
// collapses a non-zero program exit to 1):
//
//	hash <64-hex>     a definition was found and hashed
//	not_found <msg>   the file or the named definition does not exist
//	syntax <msg>      the file is not valid Go
package main

import (
	"crypto/sha256"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"reflect"
	"strings"
)

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: gohash <file.go> <qualname>")
		os.Exit(64)
	}
	fmt.Println(result(os.Args[1], os.Args[2]))
}

func result(path, qual string) string {
	if _, err := os.Stat(path); err != nil {
		return "not_found file " + path
	}
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, path, nil, 0) // flags=0: drop all comments
	if err != nil {
		return "syntax " + oneline(err.Error())
	}
	node := findDef(file, qual)
	if node == nil {
		return "not_found def " + qual
	}
	var sb strings.Builder
	if err := ast.Fprint(&sb, fset, node, fieldFilter); err != nil {
		return "syntax " + oneline(err.Error())
	}
	sum := sha256.Sum256([]byte(sb.String()))
	return fmt.Sprintf("hash %x", sum)
}

func oneline(s string) string { return strings.ReplaceAll(strings.TrimSpace(s), "\n", " ") }

var posType = reflect.TypeOf(token.Pos(0))

// fieldFilter drops what is not behaviour: source positions, and Doc/Comment
// groups. Everything in the signature and body is kept.
func fieldFilter(name string, value reflect.Value) bool {
	if name == "Doc" || name == "Comment" {
		return false
	}
	return value.Type() != posType
}

// findDef resolves a top-level func/type name, or "Type.method" for a method.
func findDef(file *ast.File, qual string) ast.Node {
	if recv, meth, ok := strings.Cut(qual, "."); ok {
		for _, d := range file.Decls {
			if fd, ok := d.(*ast.FuncDecl); ok && fd.Recv != nil &&
				fd.Name.Name == meth && recvName(fd) == recv {
				return fd
			}
		}
		return nil
	}
	for _, d := range file.Decls {
		switch decl := d.(type) {
		case *ast.FuncDecl:
			if decl.Recv == nil && decl.Name.Name == qual {
				return decl
			}
		case *ast.GenDecl:
			for _, spec := range decl.Specs {
				if ts, ok := spec.(*ast.TypeSpec); ok && ts.Name.Name == qual {
					return ts
				}
			}
		}
	}
	return nil
}

func recvName(fd *ast.FuncDecl) string {
	t := fd.Recv.List[0].Type
	if star, ok := t.(*ast.StarExpr); ok {
		t = star.X
	}
	if id, ok := t.(*ast.Ident); ok {
		return id.Name
	}
	return ""
}

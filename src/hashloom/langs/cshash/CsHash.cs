// Command CsHash prints the sha256 of a C# definition's normalised token stream.
//
// Usage: dotnet CsHash.dll <file.cs> <Qualname>
//
// Qualname is a top-level (non-nested) type name in any namespace, "Type.Member"
// for a method, constructor, property, field, or event, or a dotted path through
// nested types ("Outer.Inner.Member"). The hash is taken over the definition's
// raw token stream with all trivia excluded, so formatting, comments, and
// XML-doc edits never change it, but a signature or body change does. All
// overloads of a named member hash together, in source order. This is the C#
// analogue of hashloom's javac-tree hash for Java and ast.dump hash for Python.
//
// The result is one line on stdout, exit 0:
//
//   hash <64-hex>       a definition was found and hashed
//   not_found <msg>     the file or the named definition does not exist
//   syntax <msg>        the file is not valid C#
//
// The C# adapter compiles this file once per SDK version with the .NET SDK's
// own csc, against the SDK's own bundled Roslyn (Microsoft.CodeAnalysis*), so
// there are no package dependencies and no network access.

using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

public static class CsHash
{
    public static int Main(string[] args)
    {
        if (args.Length != 2)
        {
            System.Console.Error.WriteLine("usage: dotnet CsHash.dll <file.cs> <qualname>");
            return 64;
        }
        System.Console.WriteLine(Result(args[0], args[1]));
        return 0;
    }

    static string Result(string path, string qual)
    {
        if (!File.Exists(path))
        {
            return "not_found file " + path;
        }
        var tree = CSharpSyntaxTree.ParseText(File.ReadAllText(path));
        foreach (var d in tree.GetDiagnostics())
        {
            if (d.Severity == DiagnosticSeverity.Error)
            {
                return "syntax " + Oneline(d.GetMessage());
            }
        }
        var defs = FindDefs(tree.GetCompilationUnitRoot(), qual);
        if (defs.Count == 0)
        {
            return "not_found def " + qual;
        }
        var dump = new StringBuilder();
        foreach (var def in defs)
        {
            foreach (var tok in def.DescendantTokens())
            {
                // length-prefixed so adjacent tokens can never merge ambiguously;
                // CRLF-normalised so raw-string/verbatim content hashes the same
                // cross-OS (the same stance JavaHash takes on its tree dump)
                var text = tok.Text.Replace("\r\n", "\n");
                dump.Append(text.Length).Append(':').Append(text).Append('\n');
            }
        }
        return "hash " + Sha256Hex(dump.ToString());
    }

    // Resolves "Type", "Type.Member", or "Outer.Inner.Member": the first segment
    // names a non-nested type in any namespace (block-scoped or file-scoped),
    // further segments descend nested types by simple name, and the final
    // unmatched segment names members — all members with that name (overloads)
    // are returned in source order. "Type.Type" names the constructors.
    static List<SyntaxNode> FindDefs(CompilationUnitSyntax unit, string qual)
    {
        var segments = qual.Split('.');
        var defs = new List<SyntaxNode>();
        BaseTypeDeclarationSyntax current = null;
        // descend only through namespaces, so nested types are never top-level
        foreach (var type in unit
                 .DescendantNodes(n => n is CompilationUnitSyntax || n is BaseNamespaceDeclarationSyntax)
                 .OfType<BaseTypeDeclarationSyntax>())
        {
            if (type.Identifier.Text == segments[0])
            {
                current = type;
                break;
            }
        }
        if (current == null)
        {
            return defs;
        }
        int i = 1;
        while (i < segments.Length)
        {
            BaseTypeDeclarationSyntax nested = null;
            if (current is TypeDeclarationSyntax outer)
            {
                foreach (var member in outer.Members)
                {
                    if (member is BaseTypeDeclarationSyntax t && t.Identifier.Text == segments[i])
                    {
                        nested = t;
                        break;
                    }
                }
            }
            if (nested == null)
            {
                break;
            }
            current = nested;
            i++;
        }
        if (i == segments.Length)
        {
            defs.Add(current);
            return defs;
        }
        if (i != segments.Length - 1)
        {
            return defs;
        }
        var name = segments[i];
        if (!(current is TypeDeclarationSyntax type2))
        {
            return defs; // enums have no named members to hash individually
        }
        bool wantCtor = current.Identifier.Text == name;
        foreach (var member in type2.Members)
        {
            if ((member is MethodDeclarationSyntax m && m.Identifier.Text == name)
                || (member is ConstructorDeclarationSyntax && wantCtor)
                || (member is PropertyDeclarationSyntax p && p.Identifier.Text == name)
                || (member is EventDeclarationSyntax e && e.Identifier.Text == name)
                || (member is FieldDeclarationSyntax f
                    && f.Declaration.Variables.Any(v => v.Identifier.Text == name))
                || (member is EventFieldDeclarationSyntax ef
                    && ef.Declaration.Variables.Any(v => v.Identifier.Text == name)))
            {
                defs.Add(member);
            }
        }
        return defs;
    }

    static string Sha256Hex(string s)
    {
        var sum = SHA256.HashData(Encoding.UTF8.GetBytes(s));
        var hex = new StringBuilder(sum.Length * 2);
        foreach (var b in sum)
        {
            hex.Append(b.ToString("x2"));
        }
        return hex.ToString();
    }

    static string Oneline(string s)
    {
        var parts = s.Split((char[])null, System.StringSplitOptions.RemoveEmptyEntries);
        return string.Join(" ", parts);
    }
}

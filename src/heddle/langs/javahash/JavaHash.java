// Command JavaHash prints the sha256 of a Java definition's normalised AST.
//
// Usage: java JavaHash.java <file.java> <Qualname>
//
// Qualname is a top-level type name, "Type.member" for a method or field, or a
// dotted path through nested types ("Outer.Inner.member"). The hash is taken
// over javac's pretty-printed parse tree, so formatting, comments, and javadoc
// edits never change it, but a signature or body change does. All overloads of
// a named method hash together, in source order. This is the Java analogue of
// heddle's Python ast.dump hash and Go ast.Fprint hash.
//
// The result is one line on stdout, exit 0:
//
//	hash <64-hex>       a definition was found and hashed
//	not_found <msg>     the file or the named definition does not exist
//	syntax <msg>        the file is not valid Java
//	notoolchain <msg>   no system compiler (running on a JRE, not a JDK)
//
// Runs via Java's single-file source launcher (JDK >= 11); only JDK modules
// (java.compiler, jdk.compiler) are used, so there are no dependencies.

import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.Tree;
import com.sun.source.tree.VariableTree;
import com.sun.source.util.JavacTask;

import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;

public class JavaHash {

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("usage: java JavaHash.java <file.java> <qualname>");
            System.exit(64);
        }
        System.out.println(result(args[0], args[1]));
    }

    static String result(String path, String qual) throws Exception {
        File file = new File(path);
        if (!file.isFile()) {
            return "not_found file " + path;
        }
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            return "notoolchain no system Java compiler (a JDK is required, not a JRE)";
        }
        DiagnosticCollector<JavaFileObject> diags = new DiagnosticCollector<>();
        try (StandardJavaFileManager fm =
                compiler.getStandardFileManager(diags, null, StandardCharsets.UTF_8)) {
            JavacTask task = (JavacTask) compiler.getTask(
                    null, fm, diags, List.of(), null, fm.getJavaFileObjects(file));
            CompilationUnitTree unit = null;
            for (CompilationUnitTree u : task.parse()) {
                unit = u;
                break;
            }
            for (Diagnostic<? extends JavaFileObject> d : diags.getDiagnostics()) {
                if (d.getKind() == Diagnostic.Kind.ERROR) {
                    return "syntax " + oneline(d.getMessage(null));
                }
            }
            if (unit == null) {
                return "syntax no compilation unit in " + path;
            }
            List<Tree> defs = findDefs(unit, qual);
            if (defs.isEmpty()) {
                return "not_found def " + qual;
            }
            StringBuilder dump = new StringBuilder();
            for (Tree def : defs) {
                dump.append(def.toString()).append('\n');
            }
            // javac's pretty printer emits the platform line separator; hash
            // LF-normalised so the same source hashes identically cross-OS
            return "hash " + sha256Hex(dump.toString().replace("\r\n", "\n"));
        }
    }

    // Resolves "Type", "Type.member", or "Outer.Inner.member": descend nested
    // types by simple name; the final unmatched segment names members, and all
    // members with that name (overloads) are returned in source order.
    static List<Tree> findDefs(CompilationUnitTree unit, String qual) {
        String[] segments = qual.split("\\.");
        ClassTree current = null;
        for (Tree decl : unit.getTypeDecls()) {
            if (decl instanceof ClassTree
                    && ((ClassTree) decl).getSimpleName().contentEquals(segments[0])) {
                current = (ClassTree) decl;
                break;
            }
        }
        if (current == null) {
            return List.of();
        }
        int i = 1;
        while (i < segments.length) {
            ClassTree nested = null;
            for (Tree member : current.getMembers()) {
                if (member instanceof ClassTree
                        && ((ClassTree) member).getSimpleName().contentEquals(segments[i])) {
                    nested = (ClassTree) member;
                    break;
                }
            }
            if (nested == null) {
                break;
            }
            current = nested;
            i++;
        }
        if (i == segments.length) {
            return List.of(current);
        }
        if (i != segments.length - 1) {
            return List.of();
        }
        String name = segments[i];
        // javac stores constructor names as <init> at parse time, so
        // "Type.Type" (the source-level spelling) must match them too
        boolean wantCtor = current.getSimpleName().contentEquals(name);
        List<Tree> members = new ArrayList<>();
        for (Tree member : current.getMembers()) {
            if (member instanceof MethodTree) {
                MethodTree method = (MethodTree) member;
                if (method.getName().contentEquals(name)
                        || (wantCtor && method.getName().contentEquals("<init>"))) {
                    members.add(member);
                }
            } else if (member instanceof VariableTree
                    && ((VariableTree) member).getName().contentEquals(name)) {
                members.add(member);
            }
        }
        return members;
    }

    static String sha256Hex(String s) throws Exception {
        byte[] sum = MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));
        StringBuilder hex = new StringBuilder(sum.length * 2);
        for (byte b : sum) {
            hex.append(String.format("%02x", b));
        }
        return hex.toString();
    }

    static String oneline(String s) {
        return s.trim().replaceAll("\\s+", " ");
    }
}

from app.services.document_folders import build_document_folder_tree


def test_build_document_folder_tree_counts_subtree_documents():
    root = build_document_folder_tree(
        [
            "a/b/file1.txt",
            "a/b/file2.txt",
            "a/c/file3.txt",
            "d/file4.txt",
            None,  # type: ignore[list-item]
            "",
        ],
        total_documents=6,
        max_depth=20,
    )

    assert root.path == ""
    assert root.documents == 6

    by_name = {c.name: c for c in root.children}
    assert by_name["a"].documents == 3
    assert by_name["d"].documents == 1

    a_children = {c.name: c for c in by_name["a"].children}
    assert a_children["b"].documents == 2
    assert a_children["c"].documents == 1


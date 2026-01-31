def test_check_dependency_success():
    from app.core.optional_deps import check_dependency

    ok, err = check_dependency("json", attr="loads")
    assert ok is True
    assert err is None


def test_check_dependency_missing_module():
    from app.core.optional_deps import check_dependency

    ok, err = check_dependency("this_module_should_not_exist_abcdefg")
    assert ok is False
    assert isinstance(err, str) and err


def test_check_dependency_missing_attr():
    from app.core.optional_deps import check_dependency

    ok, err = check_dependency("json", attr="this_attr_should_not_exist_abcdefg")
    assert ok is False
    assert isinstance(err, str) and err


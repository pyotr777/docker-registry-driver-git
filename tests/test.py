# -*- coding: utf-8 -*-

from docker_registry import testing




class TestQuery(testing.Query):
    def __init__(self):
        self.scheme = 'git'


class TestDriver(testing.Driver):
    def __init__(self):
        self.scheme = 'git'
        self.path = ''
        self.config = testing.Config({})

    def setUp(self):
        super(TestDriver, self).setUp()
        self._storage._swift_connection.put_container(
            self._storage._swift_container
        )

    def tearDown(self):
        super(TestDriver, self).tearDown()
        self._storage._swift_connection.delete_container(
            self._storage._swift_container
        )

    # XXX ignoring this
    # swiftclient doesn't raise if what we remove doesn't exist, which is bad!
    def test_remove_inexistent(self):
        pass

    def test_list_directory(self):
        # Test with root directory
        super(TestDriver, self).test_list_directory()
        self.tearDown()

        # Test with custom root directory
        self.config = testing.Config({'storage_path': '/foo'})
        self.setUp()
        super(TestDriver, self).test_list_directory()

    def test_list_directory_with_subdir(self):
        # Test with root directory
        super(TestDriver, self).test_list_directory_with_subdir()
        self.tearDown()

        # Test with custom root directory
        self.config = testing.Config({'storage_path': '/foo'})
        self.setUp()
        super(TestDriver, self).test_list_directory_with_subdir()

    

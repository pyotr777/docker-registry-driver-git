# -*- coding: utf-8 -*-

import logging

logger = logging.getLogger(__name__)

class TestQuery(object):
    def test_package(self):
        import git
        g = git.cmd.Git()
        logger.debug("Got git %s" % g.version_info)

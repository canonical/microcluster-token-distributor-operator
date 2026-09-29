DIRNAME := $(shell basename $(CURDIR))
LIB := lib/charms/microcluster_token_distributor/v0/token_distributor.py
PARALLEL ?=
TESTSUITEFLAGS ?=

build:
	charmcraft pack -v

secret:
	charmcraft login \
		--export=secret \
		--charm=microcluster-token-distributor \
		--permission=package-manage-metadata \
		--permission=package-manage-releases \
		--permission=package-manage-revisions \
		--permission=package-view-metadata \
		--permission=package-view-releases \
		--permission=package-view-revisions \
		--ttl=31536000  # 365 days

check-integration:
ifeq ($(PARALLEL),)
	tox -e integration -- $(TESTSUITEFLAGS)
else
	tox -e integration -- -n $(PARALLEL) $(TESTSUITEFLAGS)
endif

clean:
	charmcraft clean
	rm -f microcluster-token-distributor_*.charm
	rm -f .charmhub.secret

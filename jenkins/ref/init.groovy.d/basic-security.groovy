import hudson.model.User
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import hudson.security.HudsonPrivateSecurityRealm
import jenkins.model.Jenkins

def jenkins = Jenkins.get()

def adminId = System.getenv('JENKINS_ADMIN_ID') ?: 'admin'
def adminPassword = System.getenv('JENKINS_ADMIN_PASSWORD') ?: 'admin'

def realm = jenkins.getSecurityRealm()
if (!(realm instanceof HudsonPrivateSecurityRealm)) {
    realm = new HudsonPrivateSecurityRealm(false)
    jenkins.setSecurityRealm(realm)
}

if (User.getById(adminId, false) == null) {
    realm.createAccount(adminId, adminPassword)
}

def strategy = jenkins.getAuthorizationStrategy()
if (!(strategy instanceof FullControlOnceLoggedInAuthorizationStrategy)) {
    strategy = new FullControlOnceLoggedInAuthorizationStrategy()
    strategy.setAllowAnonymousRead(false)
    jenkins.setAuthorizationStrategy(strategy)
}

jenkins.setNumExecutors(1)
jenkins.save()
